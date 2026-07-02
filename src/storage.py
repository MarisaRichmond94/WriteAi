"""Storage layer: ChromaDB (semantic search) + SQLite (structured lookups).

Every chunk is written to both stores under the same chunk_id, so the query
layer can move freely between semantic and structured retrieval.

ChromaDB : chunk text as the document, our own embeddings passed explicitly
           (no Chroma-side embedding function — we control the model), and a
           flattened scalar metadata dict for filtering.
SQLite   : a `chunks` table with the full metadata (list fields as JSON), plus
           normalized side tables for the query-critical lists so questions
           like "every scene where X appears" are a plain indexed SELECT.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id            TEXT PRIMARY KEY,
    book_number         INTEGER NOT NULL,
    book_title          TEXT NOT NULL,
    chapter_number      INTEGER NOT NULL,
    chapter_kind        TEXT,
    scene_number        INTEGER,
    chunk_index         INTEGER,
    pov_character       TEXT,
    date_line           TEXT,
    part_number         INTEGER,
    part_title          TEXT,
    word_count          INTEGER,
    timeline_position   TEXT,
    text                TEXT NOT NULL,
    text_hash           TEXT NOT NULL,
    metadata_json       TEXT          -- the full metadata dict, verbatim
);
CREATE INDEX IF NOT EXISTS idx_chunks_position
    ON chunks(book_number, chapter_number, chunk_index);
CREATE INDEX IF NOT EXISTS idx_chunks_pov ON chunks(pov_character);

CREATE TABLE IF NOT EXISTS characters (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    name     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name);
CREATE INDEX IF NOT EXISTS idx_characters_chunk ON characters(chunk_id);

CREATE TABLE IF NOT EXISTS locations (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    name     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_locations_name ON locations(name);
CREATE INDEX IF NOT EXISTS idx_locations_chunk ON locations(chunk_id);

CREATE TABLE IF NOT EXISTS character_knowledge (
    chunk_id  TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    character TEXT NOT NULL,
    learns    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_character ON character_knowledge(character);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunk ON character_knowledge(chunk_id);

CREATE TABLE IF NOT EXISTS foreshadowing (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    detail   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_foreshadowing_chunk ON foreshadowing(chunk_id);

CREATE TABLE IF NOT EXISTS unresolved_questions (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    question TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_chunk ON unresolved_questions(chunk_id);
"""


def slugify(name: str) -> str:
    """Series name -> ChromaDB collection name (3-63 chars, [a-z0-9._-])."""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return (slug or "series")[:63].ljust(3, "x")


class SeriesStore:
    def __init__(self, cfg):
        import chromadb  # heavy import, keep at call time

        cfg.ensure_data_dirs()
        self._chroma = chromadb.PersistentClient(path=str(cfg.chroma_dir))
        self.collection = self._chroma.get_or_create_collection(
            name=slugify(cfg.series_name),
            metadata={"hnsw:space": "cosine"},
        )
        # One SQLite connection per thread: the web server calls this from a
        # threadpool, and sharing a single connection across threads
        # interleaves cursors. SQLite coordinates between connections.
        import threading
        self._cfg_path = cfg.sqlite_path
        self._local = threading.local()
        self.db.executescript(_SCHEMA)
        self.db.commit()

    @property
    def db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._cfg_path, check_same_thread=False)
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
        return conn

    # ── writes ──────────────────────────────────────────────────────────────

    def upsert_chunks(self, records: list[dict]) -> None:
        """records: [{chunk, metadata (dict|None), embedding, text_hash}, ...]

        Idempotent: existing rows/vectors for the same chunk_id are replaced.
        """
        if not records:
            return
        self._upsert_chroma(records)
        self._upsert_sqlite(records)

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self.collection.delete(ids=chunk_ids)
        self.db.executemany("DELETE FROM chunks WHERE chunk_id = ?",
                            [(cid,) for cid in chunk_ids])
        self.db.commit()

    def delete_book(self, book_number: int) -> list[str]:
        """Remove every chunk of a book (used when re-ingesting). Returns ids."""
        rows = self.db.execute(
            "SELECT chunk_id FROM chunks WHERE book_number = ?", (book_number,)
        ).fetchall()
        ids = [r[0] for r in rows]
        self.delete_chunks(ids)
        return ids

    # ── reads ───────────────────────────────────────────────────────────────

    def counts(self) -> dict:
        c = {"chroma_chunks": self.collection.count()}
        for table in ("chunks", "characters", "locations", "character_knowledge",
                      "foreshadowing", "unresolved_questions"):
            c[table] = self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return c

    def semantic_search(self, query_embedding: list[float], top_k: int,
                        where: dict | None = None) -> list[dict]:
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for cid, doc, meta, dist in zip(result["ids"][0], result["documents"][0],
                                        result["metadatas"][0], result["distances"][0]):
            hits.append({"chunk_id": cid, "text": doc, "metadata": meta,
                         "distance": dist})
        return hits

    def chunks_with_character(self, name: str) -> list[sqlite3.Row]:
        self.db.row_factory = sqlite3.Row
        return self.db.execute(
            """SELECT c.chunk_id, c.book_number, c.book_title, c.chapter_number,
                      c.pov_character, c.date_line
               FROM chunks c JOIN characters ch ON ch.chunk_id = c.chunk_id
               WHERE ch.name LIKE ?
               ORDER BY c.book_number, c.chapter_number, c.chunk_index""",
            (f"%{name}%",),
        ).fetchall()

    # ── internals ───────────────────────────────────────────────────────────

    def _upsert_chroma(self, records: list[dict]) -> None:
        ids, embeddings, documents, metadatas = [], [], [], []
        for r in records:
            chunk, meta = r["chunk"], r["metadata"] or {}
            ids.append(chunk.chunk_id)
            embeddings.append(r["embedding"])
            documents.append(chunk.text)
            metadatas.append(self._chroma_metadata(chunk, meta))
        # Chroma caps batch sizes; 100 at a time is comfortably safe.
        for i in range(0, len(ids), 100):
            s = slice(i, i + 100)
            self.collection.upsert(ids=ids[s], embeddings=embeddings[s],
                                   documents=documents[s], metadatas=metadatas[s])

    @staticmethod
    def _chroma_metadata(chunk, meta: dict) -> dict:
        """Chroma metadata must be scalar-valued: lists become JSON strings,
        Nones are dropped."""
        flat = {
            "book_number": chunk.book_number,
            "book_title": chunk.book_title,
            "chapter_number": chunk.chapter_number,
            "chapter_kind": chunk.chapter_kind,
            "scene_number": chunk.scene_number,
            "chunk_index": chunk.chunk_index,
            "pov_character": chunk.pov_character,
            "date_line": chunk.date_line,
            "part_number": chunk.part_number,
            "word_count": chunk.word_count,
            "timeline_position": meta.get("timeline_position"),
            "characters_present": json.dumps(meta.get("characters_present", [])),
            "locations": json.dumps(meta.get("locations", [])),
        }
        return {k: v for k, v in flat.items() if v is not None}

    def _upsert_sqlite(self, records: list[dict]) -> None:
        cur = self.db.cursor()
        for r in records:
            chunk, meta = r["chunk"], r["metadata"] or {}
            # delete-then-insert keeps the side tables consistent (CASCADE)
            cur.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,))
            cur.execute(
                """INSERT INTO chunks (chunk_id, book_number, book_title,
                       chapter_number, chapter_kind, scene_number, chunk_index,
                       pov_character, date_line, part_number, part_title,
                       word_count, timeline_position, text, text_hash, metadata_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (chunk.chunk_id, chunk.book_number, chunk.book_title,
                 chunk.chapter_number, chunk.chapter_kind, chunk.scene_number,
                 chunk.chunk_index, chunk.pov_character, chunk.date_line,
                 chunk.part_number, chunk.part_title, chunk.word_count,
                 meta.get("timeline_position"), chunk.text, r["text_hash"],
                 json.dumps(meta, ensure_ascii=False) if meta else None),
            )
            cur.executemany(
                "INSERT INTO characters (chunk_id, name) VALUES (?, ?)",
                [(chunk.chunk_id, n) for n in meta.get("characters_present", [])])
            cur.executemany(
                "INSERT INTO locations (chunk_id, name) VALUES (?, ?)",
                [(chunk.chunk_id, n) for n in meta.get("locations", [])])
            cur.executemany(
                "INSERT INTO character_knowledge (chunk_id, character, learns) VALUES (?, ?, ?)",
                [(chunk.chunk_id, ch, fact)
                 for ch, facts in meta.get("character_knowledge_updates", {}).items()
                 for fact in facts])
            cur.executemany(
                "INSERT INTO foreshadowing (chunk_id, detail) VALUES (?, ?)",
                [(chunk.chunk_id, d) for d in meta.get("foreshadowing", [])])
            cur.executemany(
                "INSERT INTO unresolved_questions (chunk_id, question) VALUES (?, ?)",
                [(chunk.chunk_id, q) for q in meta.get("unresolved_questions", [])])
        self.db.commit()

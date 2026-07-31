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
import time

from .notes import pair_quotes

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
    chunk_id     TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    character    TEXT NOT NULL,
    learns       TEXT NOT NULL,
    source_quote TEXT           -- verbatim manuscript sentence(s), if any
);
CREATE INDEX IF NOT EXISTS idx_knowledge_character ON character_knowledge(character);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunk ON character_knowledge(chunk_id);

CREATE TABLE IF NOT EXISTS foreshadowing (
    chunk_id     TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    detail       TEXT NOT NULL,
    source_quote TEXT
);
CREATE INDEX IF NOT EXISTS idx_foreshadowing_chunk ON foreshadowing(chunk_id);

CREATE TABLE IF NOT EXISTS unresolved_questions (
    chunk_id     TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    question     TEXT NOT NULL,
    source_quote TEXT
);
CREATE INDEX IF NOT EXISTS idx_questions_chunk ON unresolved_questions(chunk_id);

-- Story-chronological placement of each chapter (ENABLE_STORY_ORDER).
-- Populated by scripts/resolve_chronology.py: story_year is a small relative
-- epoch consistent ACROSS books (never real calendar years — the date lines
-- carry no years); month/day are parsed deterministically from the chapter's
-- date line. Rows with manual_override=1 are never rewritten by the script.
CREATE TABLE IF NOT EXISTS chapter_timeline (
    book_number     INTEGER NOT NULL,
    chapter_number  INTEGER NOT NULL,
    story_year      INTEGER NOT NULL,
    month           INTEGER,          -- 1-12, NULL when the date line has none
    day             INTEGER,          -- 1-31, NULL when the date line has none
    temporal_mode   TEXT NOT NULL DEFAULT 'primary',
                    -- 'primary' | 'flashback' | 'flashforward' | 'unknown'
    confidence      REAL,
    rationale       TEXT,
    manual_override INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (book_number, chapter_number)
);

-- BM25 keyword index over chunk text (external content: rows shadow `chunks`).
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
    USING fts5(text, content='chunks', content_rowid='rowid');
"""


def migrate_schema(db: sqlite3.Connection) -> None:
    """Idempotent post-DDL migrations for stores created before a column
    existed (CREATE TABLE IF NOT EXISTS never alters an existing table).
    Guarded by pragma_table_info so re-running is a no-op; nullable columns
    only, so old rows stay readable and old queries keep working."""
    for table in ("foreshadowing", "unresolved_questions", "character_knowledge"):
        cols = {row[1] for row in
                db.execute(f"SELECT * FROM pragma_table_info('{table}')")}
        if "source_quote" not in cols:
            log.info("migrating %s: adding source_quote column", table)
            db.execute(f"ALTER TABLE {table} ADD COLUMN source_quote TEXT")

    # Stable Loom identity (KAN-12). book_number and book_title are derived
    # from the folder name: book_number survives a rename but breaks on
    # insertion or reordering, book_title does the reverse. Loom's cuids
    # survive both, and reach us through the manifest sidecar.
    #
    # Nullable, and both old columns are kept, so existing rows and every
    # existing query keep working. Rows written before a book has been
    # canon-exported will hold NULL — readers must fall back rather than
    # assume a match.
    for table in ("chunks", "events", "chapter_timeline",
                  "chapter_summaries", "location_map_v2"):
        cols = {row[1] for row in
                db.execute(f"SELECT * FROM pragma_table_info('{table}')")}
        if not cols:
            continue  # table not created yet on this store
        for col in ("loom_book_id", "loom_series_id"):
            if col not in cols:
                log.info("migrating %s: adding %s column", table, col)
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")


def slugify(name: str) -> str:
    """Series name -> ChromaDB collection name (3-63 chars, [a-z0-9._-]).

    LEGACY naming. Retained to find and migrate collections created before
    KAN-10, and as the fallback when no stable id is available. New stores use
    stable_collection_name().
    """
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return (slug or "series")[:63].ljust(3, "x")


def stable_collection_name(loom_series_id: str) -> str:
    """Loom series cuid -> ChromaDB collection name (KAN-10).

    The collection used to be named `slugify(SERIES_NAME)`, which made the
    entire vector index addressable by a *display* string. Changing SERIES_NAME
    meant get_or_create_collection quietly created a NEW, EMPTY collection:
    every query returned nothing and the index looked destroyed, while the real
    one sat untouched under the old name. Silent, and indistinguishable from
    catastrophic loss.

    cuids are already lowercase alphanumeric, so they satisfy Chroma's
    [a-z0-9._-] and 3-63 char rules without munging. The prefix keeps the name
    self-describing in `chroma list` output.
    """
    return f"series-{loom_series_id}"[:63].ljust(3, "x")


def _resolve_loom_series_id(cfg) -> str | None:
    """Loom's series cuid from the manifest sidecars, or None (KAN-10).

    Never raises: a store that cannot resolve identity must still open, on the
    legacy display-name collection, exactly as it did before.
    """
    try:
        from .discovery import discover_books
        return next((b.loom_series_id for b in discover_books(cfg)
                     if b.loom_series_id), None)
    except Exception:
        log.warning("could not resolve the Loom series id — the vector index "
                    "stays on its display-name collection", exc_info=True)
        return None


class SeriesStore:
    def __init__(self, cfg):
        cfg.ensure_data_dirs()
        self._chroma_dir = str(cfg.chroma_dir)
        self._cfg = cfg
        # Name the collection by Loom's stable series id where we have one
        # (KAN-10); fall back to the display-name slug when nothing has been
        # canon-exported yet. _open_chroma migrates a legacy-named collection
        # across in place.
        self._legacy_collection_name = slugify(cfg.series_name)
        loom_series_id = _resolve_loom_series_id(cfg)
        self._collection_name = (stable_collection_name(loom_series_id)
                                 if loom_series_id else self._legacy_collection_name)
        self._open_chroma()
        self._notes_collection = None  # companion notes index; created lazily
        # One SQLite connection per thread: the web server calls this from a
        # threadpool, and sharing a single connection across threads
        # interleaves cursors. SQLite coordinates between connections.
        import threading
        self._cfg_path = cfg.sqlite_path
        # book_number -> (loom_book_id, loom_series_id); built lazily, once.
        self._loom_id_map: dict[int, tuple[str | None, str | None]] | None = None
        self._local = threading.local()
        self.db.executescript(_SCHEMA)
        migrate_schema(self.db)
        self._backfill_fts()
        self.db.commit()

    def _migrate_legacy_collections(self) -> None:
        """Rename display-name collections onto the stable id (KAN-10).

        A RENAME, not a rebuild: Chroma's modify(name=...) rewrites the
        collection record only, so the embeddings are untouched. Re-embedding
        would cost real API spend for zero benefit.

        Ordering matters. This runs BEFORE get_or_create_collection — call it
        after and you have already created the new empty collection, at which
        point the rename can't happen and the old index is orphaned. That is
        precisely the failure this whole change exists to prevent.

        No-op when there is nothing to migrate, when the target already exists,
        or when we never resolved a stable id.
        """
        if self._collection_name == self._legacy_collection_name:
            return  # no stable id; nothing to migrate onto

        try:
            existing = {c.name for c in self._chroma.list_collections()}
        except Exception:
            log.warning("could not list Chroma collections — skipping the "
                        "stable-id migration this run", exc_info=True)
            return

        # Main collection, then its companion notes index. Same rule for both.
        pairs = [
            (self._legacy_collection_name, self._collection_name),
            (f"{self._legacy_collection_name[:57]}-notes",
             f"{self._collection_name[:57]}-notes"),
        ]
        for old, new in pairs:
            if new in existing or old not in existing:
                continue
            try:
                self._chroma.get_collection(name=old).modify(name=new)
                log.info("migrated Chroma collection %r -> %r (rename only; "
                         "embeddings untouched)", old, new)
            except Exception:
                log.error("failed to rename Chroma collection %r -> %r. The "
                          "index is NOT lost — it remains under the old name. "
                          "Queries will use a new empty collection until this "
                          "is resolved.", old, new, exc_info=True)

    def _open_chroma(self) -> None:
        """(Re)open the Chroma client and collection from disk."""
        import chromadb  # heavy import, keep at call time

        self._chroma = chromadb.PersistentClient(path=self._chroma_dir)
        self._migrate_legacy_collections()
        self.collection = self._chroma.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        # Exhaustive-depth vector search: at this corpus scale (~1.4k chunks)
        # an ef_search beyond the collection size makes HNSW queries exact AND
        # deterministic across processes (chroma 1.x's approximate path flips
        # near-tie ranks per process, which breaks eval gating) at sub-ms cost.
        # Idempotent: modify() only runs when the stored value is lower.
        # Revisit if the corpus outgrows ~10k chunks.
        hnsw_cfg = (self.collection.configuration_json or {}).get("hnsw") or {}
        if hnsw_cfg.get("ef_search", 0) < 2000:
            self.collection.modify(configuration={"hnsw": {"ef_search": 2000}})

    def _requery_after_reopen(self, exc: Exception, what: str):
        """Decide whether `exc` is the stale-handle error and, if so, reopen.

        A re-ingest subprocess rewrites the on-disk segments underneath this
        process's cached client, which then serves an inconsistent in-memory
        view and fails with `Internal error: Error finding id`. AppState
        rebuilds the store when it hears about a re-ingest, but it only hears
        about the ones this server started — an ingest run from the CLI, or a
        reload that lands mid-query, leaves the handle stale with nobody to
        fix it. Reopening from disk here is cheap and idempotent, and turns a
        dead query into a slow one.

        Returns True when the caller should retry; re-raises anything else.
        """
        if "Error finding id" not in str(exc):
            raise exc
        log.warning("%s hit a stale Chroma handle (%s) — reopening the "
                    "collection and retrying once", what, exc)
        self._open_chroma()
        self._notes_collection = None
        return True

    def _backfill_fts(self) -> None:
        """One-time idempotent index build for stores created before chunks_fts
        existed. New/updated rows are kept in sync by the write paths.

        NB: on an external-content FTS5 table, `COUNT(*) FROM chunks_fts` reads
        through to the content table, so the real index size must come from the
        chunks_fts_docsize shadow table (one row per indexed document)."""
        n_fts = self.db.execute("SELECT COUNT(*) FROM chunks_fts_docsize").fetchone()[0]
        n_chunks = self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if n_fts == 0 and n_chunks > 0:
            log.info("building chunks_fts index for %d existing chunks", n_chunks)
            self.db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")

    @property
    def db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._cfg_path, check_same_thread=False)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")    # concurrent reads + 1 writer; survives DB rebuilds
            conn.execute("PRAGMA busy_timeout = 30000")  # wait up to 30s on contention instead of erroring
            self._local.conn = conn
        return conn

    def _write_with_retry(self, write) -> None:
        """Run a SQLite write, retrying on transient 'database is locked'.

        busy_timeout already makes each statement wait out a competing writer,
        but the ingest subprocess and the always-on server write to this DB from
        separate processes (e.g. a prior book's post-ingest GC / index reload
        racing the next book's ingest), and a long or bursty writer can still
        exceed the timeout. Left unhandled, the OperationalError aborts the
        whole run — and because ingest.py only records chunk hashes on success,
        the book stays permanently 'behind' and is re-triggered on every Loom
        export (the failure loop). Retrying after rolling back the partial
        transaction keeps a transient lock from stranding a book. The writes
        here are idempotent (delete-then-insert by chunk_id), so a full retry
        is safe.

        The budget is sized against the longest realistic hold — an enrichment
        pass, which writes between LLM calls — not against a momentary
        collision: 8 attempts of (30s busy_timeout + exponential backoff capped
        at 30s) is roughly a 5-minute ceiling. Waiting out a slow writer costs
        the sync some latency; giving up costs it the whole run."""
        attempts, max_delay = 8, 30.0
        for attempt in range(1, attempts + 1):
            try:
                write()
                return
            except sqlite3.OperationalError as e:
                # Roll back either way: on the final attempt too, so a store
                # that outlives this call isn't left holding a partial txn
                # (and, with it, the write lock the next writer needs).
                self.db.rollback()
                if "locked" not in str(e).lower() or attempt == attempts:
                    raise
                delay = min(2.0 ** (attempt - 1), max_delay)
                log.warning("SQLite write locked (attempt %d/%d); retrying in %.1fs",
                            attempt, attempts, delay)
                time.sleep(delay)

    # ── writes ──────────────────────────────────────────────────────────────

    def upsert_chunks(self, records: list[dict]) -> None:
        """records: [{chunk, metadata (dict|None), embedding, text_hash}, ...]

        Idempotent: existing rows/vectors for the same chunk_id are replaced.

        SQLite goes first because it is the write that can fail: it contends
        with the always-on server for the single write lock, while Chroma has
        no such competition. Writing vectors first meant a lock failure left
        new embeddings pointing at old row text, so semantic search returned
        prose that no longer matched the chunk. In this order the worst case
        is rows without refreshed vectors — retrieval degrades, but never
        serves the wrong text. Either way the run aborts before ingest.py
        records the chunk hashes, so the next sync repairs it.
        """
        if not records:
            return
        self._write_with_retry(lambda: self._upsert_sqlite(records))
        self._upsert_chroma(records)

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self.collection.delete(ids=chunk_ids)

        def _write():
            # External-content FTS rows must be removed via the special 'delete'
            # insert form, with the old rowid+text, BEFORE the source row goes.
            self.db.executemany(
                """INSERT INTO chunks_fts(chunks_fts, rowid, text)
                   SELECT 'delete', rowid, text FROM chunks WHERE chunk_id = ?""",
                [(cid,) for cid in chunk_ids])
            self.db.executemany("DELETE FROM chunks WHERE chunk_id = ?",
                                [(cid,) for cid in chunk_ids])
            self.db.commit()
        self._write_with_retry(_write)

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
        def _query():
            return self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )

        try:
            result = _query()
        except Exception as e:
            self._requery_after_reopen(e, "semantic_search")
            result = _query()
        hits = []
        for cid, doc, meta, dist in zip(result["ids"][0], result["documents"][0],
                                        result["metadatas"][0], result["distances"][0]):
            hits.append({"chunk_id": cid, "text": doc, "metadata": meta,
                         "distance": dist})
        return hits

    def keyword_search(self, query_text: str, n: int, scope=None) -> list[dict]:
        """BM25 keyword search over chunk text via FTS5.

        Returns hits in the same shape as semantic_search ({chunk_id, text,
        metadata, distance}); distance is None (it is a vector-space notion),
        the BM25 score is exposed under 'bm25'. `scope` is an optional object
        with book_min/book_max attributes (see query_router.Scope) — the same
        book-level bound _scope_chroma applies to the vector path; finer
        chapter bounds are the caller's post-hoc filter, as for Chroma.
        """
        match = self._fts_match_query(query_text)
        if not match:
            return []
        clauses, params = ["chunks_fts MATCH ?"], [match]
        if scope is not None:
            if getattr(scope, "book_min", None) is not None:
                clauses.append("c.book_number >= ?")
                params.append(scope.book_min)
            if getattr(scope, "book_max", None) is not None:
                clauses.append("c.book_number <= ?")
                params.append(scope.book_max)
        try:
            rows = self.db.execute(
                f"""SELECT c.chunk_id, c.text, c.book_number, c.book_title,
                           c.chapter_number, c.pov_character, c.date_line,
                           bm25(chunks_fts) AS score
                    FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid
                    WHERE {' AND '.join(clauses)}
                    ORDER BY bm25(chunks_fts), c.chunk_id
                    LIMIT ?""",
                [*params, n]).fetchall()
        except sqlite3.OperationalError as e:  # pathological query text
            log.warning("keyword_search failed for %r: %s", query_text, e)
            return []
        return [{"chunk_id": cid, "text": text,
                 "metadata": {"book_number": bn, "book_title": bt,
                              "chapter_number": ch, "pov_character": pov,
                              "date_line": dl},
                 "distance": None, "bm25": score}
                for cid, text, bn, bt, ch, pov, dl, score in rows]

    @staticmethod
    def _fts_match_query(query_text: str) -> str:
        """Recall-oriented MATCH expression: each token individually quoted
        (disabling FTS5 operator syntax), joined with OR."""
        tokens = [t.replace('"', "") for t in query_text.split()]
        tokens = [t for t in tokens if any(c.isalnum() for c in t)]
        return " OR ".join(f'"{t}"' for t in tokens)

    # ── continuity-notes vector index ───────────────────────────────────────
    # A second Chroma collection holding one embedded document per
    # foreshadowing/unresolved-question row, rendered exactly as the
    # retriever's note lines (see src/notes.py). Only touched when
    # ENABLE_NOTE_RANKING is on (query path) or the backfill script runs —
    # created lazily so flag-off runs never write to the shared data dir.

    @property
    def notes(self):
        if self._notes_collection is None:
            self._notes_collection = self._chroma.get_or_create_collection(
                name=f"{self._collection_name[:57]}-notes",
                metadata={"hnsw:space": "cosine"},
            )
            # Same exhaustive-search determinism trick as the chunk collection
            # above, sized for the larger note corpus (~7k rows today).
            # Revisit if the note count outgrows ~10k.
            hnsw_cfg = (self._notes_collection.configuration_json or {}).get("hnsw") or {}
            if hnsw_cfg.get("ef_search", 0) < 10000:
                self._notes_collection.modify(
                    configuration={"hnsw": {"ef_search": 10000}})
        return self._notes_collection

    def notes_count(self) -> int:
        return self.notes.count()

    def upsert_notes(self, note_docs: list[dict]) -> None:
        """note_docs: [{id, text, embedding, metadata}] where metadata is
        {kind, book_number, chapter_number, chunk_id}. Ids are deterministic
        (src/notes.py), so re-upserting the same rows is idempotent."""
        # collapse duplicate ids within the batch (Chroma rejects them)
        note_docs = list({d["id"]: d for d in note_docs}.values())
        for i in range(0, len(note_docs), 100):
            batch = note_docs[i:i + 100]
            self.notes.upsert(ids=[d["id"] for d in batch],
                              embeddings=[d["embedding"] for d in batch],
                              documents=[d["text"] for d in batch],
                              metadatas=[d["metadata"] for d in batch])

    def delete_notes_for_chunks(self, chunk_ids: list[str]) -> None:
        """Drop every note vector belonging to these chunks (called before
        re-upserting a changed chunk's notes, and when chunks are deleted)."""
        if chunk_ids:
            self.notes.delete(where={"chunk_id": {"$in": chunk_ids}})

    def note_search(self, query_embedding: list[float], n: int,
                    where: dict | None = None) -> list[tuple[str, dict]]:
        """Top-n notes by cosine similarity: [(note line text, metadata)]."""
        result = self.notes.query(query_embeddings=[query_embedding],
                                  n_results=n, where=where,
                                  include=["documents", "metadatas"])
        return list(zip(result["documents"][0], result["metadatas"][0]))

    def get_embeddings(self, chunk_ids: list[str]) -> dict[str, list]:
        """Stored chunk vectors, by id. Used by `ingest.py --re-extract` to
        re-run metadata extraction WITHOUT re-embedding unchanged chunk text.
        Ids missing from the collection are simply absent from the result."""
        out: dict[str, list] = {}
        for i in range(0, len(chunk_ids), 100):
            res = self.collection.get(ids=chunk_ids[i:i + 100],
                                      include=["embeddings"])
            embeddings = res.get("embeddings")
            if embeddings is None:
                continue
            for cid, emb in zip(res["ids"], embeddings):
                out[cid] = emb
        return out

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

    def _loom_identity(self, book_number: int) -> tuple[str | None, str | None]:
        """(loom_book_id, loom_series_id) for a book number (KAN-12).

        Without this, every chunk written after the KAN-12 backfill would carry
        NULL and the migration would silently decay as new prose is ingested.

        Cached for the life of the store: discovery walks the books directory
        and opens a manifest per book, which is far too much work to repeat for
        every chunk. Resolution failure is non-fatal — chunks are still written,
        just without stable IDs, which is the pre-KAN-12 behaviour.
        """
        if self._loom_id_map is None:
            self._loom_id_map = {}
        hit = self._loom_id_map.get(book_number)
        if hit and hit[0]:
            return hit

        # NEVER cache a miss. Loom's canon export writes the manifest
        # atomically -- temp file, then rename -- so there is a window where it
        # does not exist. A discovery pass landing in that window resolves the
        # book to None, and caching that made a TRANSIENT miss permanent for
        # the whole ingest: every chunk written afterwards silently lost its
        # stable id.
        #
        # That is not hypothetical. Marisa edited chapter 27 of The Secrets We
        # Keep while an ingest was running; the export raced the scan and those
        # two chunks were the only ones in the entire database written without
        # a loom_book_id. It went unnoticed because a missing manifest is a
        # legitimate state (a book never canon-exported) and so does not warn.
        #
        # Re-resolving costs one directory walk per unresolved book per call,
        # which only happens while something is genuinely unresolvable.
        try:
            from .discovery import discover_books
            fresh = {b.number: (b.loom_book_id, b.loom_series_id)
                     for b in discover_books(self._cfg)}
        except Exception:
            log.warning("could not resolve Loom identity — chunks for book %s "
                        "will be written without stable IDs", book_number,
                        exc_info=True)
            return (None, None)

        self._loom_id_map.update({n: v for n, v in fresh.items() if v[0]})
        resolved = fresh.get(book_number, (None, None))
        if not resolved[0]:
            log.warning("no stable Loom id for book %s — writing its chunks "
                        "without one. If a canon export was mid-write this is "
                        "transient and the next write will pick it up.",
                        book_number)
        return resolved

    def _upsert_sqlite(self, records: list[dict]) -> None:
        cur = self.db.cursor()
        for r in records:
            chunk, meta = r["chunk"], r["metadata"] or {}
            # delete-then-insert keeps the side tables consistent (CASCADE);
            # the FTS shadow row must be dropped first (external-content
            # 'delete' form needs the old rowid+text) and re-added after.
            cur.execute(
                """INSERT INTO chunks_fts(chunks_fts, rowid, text)
                   SELECT 'delete', rowid, text FROM chunks WHERE chunk_id = ?""",
                (chunk.chunk_id,))
            cur.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,))
            cur.execute(
                """INSERT INTO chunks (chunk_id, book_number, book_title,
                       chapter_number, chapter_kind, scene_number, chunk_index,
                       pov_character, date_line, part_number, part_title,
                       word_count, timeline_position, text, text_hash, metadata_json,
                       loom_book_id, loom_series_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (chunk.chunk_id, chunk.book_number, chunk.book_title,
                 chunk.chapter_number, chunk.chapter_kind, chunk.scene_number,
                 chunk.chunk_index, chunk.pov_character, chunk.date_line,
                 chunk.part_number, chunk.part_title, chunk.word_count,
                 meta.get("timeline_position"), chunk.text, r["text_hash"],
                 json.dumps(meta, ensure_ascii=False) if meta else None,
                 *self._loom_identity(chunk.book_number)),
            )
            cur.execute("INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)",
                        (cur.lastrowid, chunk.text))
            cur.executemany(
                "INSERT INTO characters (chunk_id, name) VALUES (?, ?)",
                [(chunk.chunk_id, n) for n in meta.get("characters_present", [])])
            cur.executemany(
                "INSERT INTO locations (chunk_id, name) VALUES (?, ?)",
                [(chunk.chunk_id, n) for n in meta.get("locations", [])])
            # quote lists ride alongside the value lists in the metadata,
            # index-aligned (pair_quotes pads with None for pre-quote metadata)
            knowledge_quotes = meta.get("character_knowledge_quotes") or {}
            cur.executemany(
                "INSERT INTO character_knowledge (chunk_id, character, learns, source_quote)"
                " VALUES (?, ?, ?, ?)",
                [(chunk.chunk_id, ch, fact, quote)
                 for ch, facts in meta.get("character_knowledge_updates", {}).items()
                 for fact, quote in pair_quotes(facts, knowledge_quotes.get(ch))])
            cur.executemany(
                "INSERT INTO foreshadowing (chunk_id, detail, source_quote) VALUES (?, ?, ?)",
                [(chunk.chunk_id, d, quote)
                 for d, quote in pair_quotes(meta.get("foreshadowing", []),
                                             meta.get("foreshadowing_quotes"))])
            cur.executemany(
                "INSERT INTO unresolved_questions (chunk_id, question, source_quote)"
                " VALUES (?, ?, ?)",
                [(chunk.chunk_id, q, quote)
                 for q, quote in pair_quotes(meta.get("unresolved_questions", []),
                                             meta.get("unresolved_question_quotes"))])
        self.db.commit()

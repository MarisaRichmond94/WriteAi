"""Continuity notes: shared rendering + note-doc construction.

A "note" is one foreshadowing detail or one unresolved question, rendered as
the exact line the retriever injects into prompts (eval parses the
"[Book N, Ch M]" prefix — never change the format here without updating it).

This module is the single source of truth for that rendering, so the
retriever's inline path, the ingestion-time sync, and
scripts/backfill_note_embeddings.py can never drift apart: the text stored
in the notes vector collection IS the note line the answerer sees.
"""

from __future__ import annotations

import hashlib

_LABELS = {"foreshadowing": "FORESHADOWING", "unresolved": "QUESTION"}

# (SQLite side table, value column, note kind) — consumed by the retriever's
# unranked path and by note_docs_from_db below.
NOTE_TABLES = (("foreshadowing", "detail", "foreshadowing"),
               ("unresolved_questions", "question", "unresolved"))

# (extraction-metadata key, note kind) — consumed by the ingestion-time sync.
_METADATA_KEYS = (("foreshadowing", "foreshadowing"),
                  ("unresolved_questions", "unresolved"))


def render_note(kind: str, book_number: int, chapter_number: int,
                text: str) -> str:
    """The exact note-line format the answerer (and eval) sees."""
    return f"[Book {book_number}, Ch {chapter_number}] {_LABELS[kind]}: {text}"


def note_id(kind: str, chunk_id: str, text: str) -> str:
    """Deterministic vector-doc id: the same row always maps to the same id,
    so re-running the backfill (or an incremental sync) upserts in place
    instead of accumulating duplicates."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{chunk_id}:{digest}"


def note_doc(kind: str, chunk_id: str, book_number: int, chapter_number: int,
             text: str) -> dict:
    """One notes-collection document (embedding added by the caller)."""
    return {"id": note_id(kind, chunk_id, text),
            "text": render_note(kind, book_number, chapter_number, text),
            "metadata": {"kind": kind, "book_number": book_number,
                         "chapter_number": chapter_number,
                         "chunk_id": chunk_id}}


def note_docs_from_db(db) -> list[dict]:
    """Every foreshadowing/unresolved row currently in SQLite as note docs,
    deduplicated by id (identical rows on the same chunk collapse)."""
    docs: dict[str, dict] = {}
    for table, column, kind in NOTE_TABLES:
        rows = db.execute(
            f"""SELECT t.chunk_id, c.book_number, c.chapter_number, t.{column}
                FROM {table} t JOIN chunks c ON c.chunk_id = t.chunk_id
                ORDER BY c.book_number, c.chapter_number, c.chunk_index"""
        ).fetchall()
        for cid, b, ch, value in rows:
            d = note_doc(kind, cid, b, ch, value)
            docs[d["id"]] = d
    return list(docs.values())


def note_docs_for_chunk(chunk, meta: dict) -> list[dict]:
    """Note docs for one freshly-extracted chunk (ingestion-time sync),
    deduplicated by id."""
    docs: dict[str, dict] = {}
    for key, kind in _METADATA_KEYS:
        for value in meta.get(key, []):
            d = note_doc(kind, chunk.chunk_id, chunk.book_number,
                         chunk.chapter_number, value)
            docs[d["id"]] = d
    return list(docs.values())

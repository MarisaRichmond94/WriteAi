"""Continuity notes: shared rendering + note-doc construction.

A "note" is one foreshadowing detail or one unresolved question, rendered as
the exact line the retriever injects into prompts (eval parses the
"[Book N, Ch M]" prefix — never change the format here without updating it).

When a note row carries a verbatim source_quote (extracted from the
manuscript and verified at parse time), the quote is appended after the
summary: `[Book N, Ch M] FORESHADOWING: <detail> — "<quote>"`. Rows without
a quote (all pre-quote extractions) render exactly as before.

This module is the single source of truth for that rendering, so the
retriever's inline path, the ingestion-time sync, and
scripts/backfill_note_embeddings.py can never drift apart: the text stored
in the notes vector collection IS the note line the answerer sees.
"""

from __future__ import annotations

import hashlib

_LABELS = {"foreshadowing": "FORESHADOWING", "unresolved": "QUESTION"}

# (SQLite side table, value column, note kind) — consumed by the retriever's
# unranked path and by note_docs_from_db below. All three tables also carry a
# nullable source_quote column (see src/storage.py).
NOTE_TABLES = (("foreshadowing", "detail", "foreshadowing"),
               ("unresolved_questions", "question", "unresolved"))

# (extraction-metadata key, parallel quote-list key, note kind) — consumed by
# the ingestion-time sync.
_METADATA_KEYS = (("foreshadowing", "foreshadowing_quotes", "foreshadowing"),
                  ("unresolved_questions", "unresolved_question_quotes",
                   "unresolved"))


def with_quote(text: str, source_quote: str | None) -> str:
    """Append a verbatim manuscript quote to a rendered value, when present.
    Null quotes leave the text byte-identical to the pre-quote rendering."""
    return f'{text} — "{source_quote}"' if source_quote else text


def pair_quotes(values: list, quotes) -> list[tuple]:
    """Zip a value list with its parallel quote list, padding missing/short
    quote lists with None (old metadata has no quote lists at all)."""
    quotes = list(quotes or [])
    quotes += [None] * (len(values) - len(quotes))
    return list(zip(values, quotes))


def render_note(kind: str, book_number: int, chapter_number: int,
                text: str, source_quote: str | None = None) -> str:
    """The exact note-line format the answerer (and eval) sees."""
    return (f"[Book {book_number}, Ch {chapter_number}] {_LABELS[kind]}: "
            f"{with_quote(text, source_quote)}")


def note_id(kind: str, chunk_id: str, text: str,
            source_quote: str | None = None) -> str:
    """Deterministic vector-doc id: the same row always maps to the same id,
    so re-running the backfill (or an incremental sync) upserts in place
    instead of accumulating duplicates. Quote-less rows keep their historical
    ids; a quote folds into the digest so two rows with the same summary but
    different quotes stay distinct docs."""
    payload = f"{text}\x00{source_quote}" if source_quote else text
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{chunk_id}:{digest}"


def note_doc(kind: str, chunk_id: str, book_number: int, chapter_number: int,
             text: str, source_quote: str | None = None) -> dict:
    """One notes-collection document (embedding added by the caller). The doc
    text includes the quote — verbatim prose is extra retrieval signal."""
    return {"id": note_id(kind, chunk_id, text, source_quote),
            "text": render_note(kind, book_number, chapter_number, text,
                                source_quote),
            "metadata": {"kind": kind, "book_number": book_number,
                         "chapter_number": chapter_number,
                         "chunk_id": chunk_id}}


def note_docs_from_db(db) -> list[dict]:
    """Every foreshadowing/unresolved row currently in SQLite as note docs,
    deduplicated by id (identical rows on the same chunk collapse)."""
    docs: dict[str, dict] = {}
    for table, column, kind in NOTE_TABLES:
        rows = db.execute(
            f"""SELECT t.chunk_id, c.book_number, c.chapter_number, t.{column},
                       t.source_quote
                FROM {table} t JOIN chunks c ON c.chunk_id = t.chunk_id
                ORDER BY c.book_number, c.chapter_number, c.chunk_index"""
        ).fetchall()
        for cid, b, ch, value, quote in rows:
            d = note_doc(kind, cid, b, ch, value, quote)
            docs[d["id"]] = d
    return list(docs.values())


def note_docs_for_chunk(chunk, meta: dict) -> list[dict]:
    """Note docs for one freshly-extracted chunk (ingestion-time sync),
    deduplicated by id."""
    docs: dict[str, dict] = {}
    for key, quote_key, kind in _METADATA_KEYS:
        for value, quote in pair_quotes(meta.get(key, []), meta.get(quote_key)):
            d = note_doc(kind, chunk.chunk_id, chunk.book_number,
                         chunk.chapter_number, value, quote)
            docs[d["id"]] = d
    return list(docs.values())

"""Ingestion pipeline orchestration.

Per book: extract text (read-only, staged copies) -> segment/chunk ->
LLM metadata -> embeddings -> upsert into ChromaDB + SQLite.

Phase 4 ingests whole books; Phase 5 layers hash-based change detection on
top so nightly runs only touch new/changed chunks.
"""

from __future__ import annotations

import hashlib
import logging
import shutil

from .chunker import Chunk, chunk_book
from .discovery import Book
from .extractor import MetadataExtractor, estimate_extraction_cost
from .parser import extract_text

log = logging.getLogger(__name__)


def chunk_text_hash(chunk: Chunk) -> str:
    """SHA-256 of the chunk's raw text — the unit of change detection."""
    return hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()


def load_and_chunk_book(cfg, book: Book) -> list[Chunk] | None:
    """Extract a book's text and chunk it. None if extraction failed
    (logged and skipped — never crashes the pipeline)."""
    text, method = extract_text(book.manuscript, cfg)
    if text is None:
        log.warning("skipping book %d (%s): text extraction failed",
                    book.number, book.title)
        return None
    segments, chunks = chunk_book(
        text, book_number=book.number, book_title=book.title,
        max_chunk_tokens=cfg.max_chunk_tokens,
    )
    log.info("book %d (%s): %d segments -> %d chunks via %s",
             book.number, book.title, len(segments), len(chunks), method)
    return chunks


def ingest_chunks(cfg, chunks: list[Chunk], extractor: MetadataExtractor,
                  embedder, store) -> dict:
    """Extract metadata + embeddings for `chunks` and upsert them.
    Returns a summary dict. Assumes the caller already handled cost
    confirmation and (Phase 5) change detection."""
    if not chunks:
        return {"chunks": 0}

    metadata_list = extractor.extract(chunks)
    embeddings = embedder.embed_documents([c.embedding_text for c in chunks])

    records = [
        {"chunk": c, "metadata": m, "embedding": e, "text_hash": chunk_text_hash(c)}
        for c, m, e in zip(chunks, metadata_list, embeddings)
    ]
    store.upsert_chunks(records)

    failed = sum(1 for m in metadata_list if m is None)
    return {
        "chunks": len(chunks),
        "metadata_failed": failed,
        "api_calls": extractor.usage["api_calls"],
        "input_tokens": extractor.usage["input_tokens"],
        "output_tokens": extractor.usage["output_tokens"],
        "actual_cost_usd": extractor.actual_cost_usd,
    }


def clear_staging(cfg) -> None:
    """Remove any leftover working copies (per source-protection rules)."""
    if cfg.staging_dir.exists():
        shutil.rmtree(cfg.staging_dir, ignore_errors=True)
    cfg.staging_dir.mkdir(parents=True, exist_ok=True)


def cost_estimate_for(chunks: list[Chunk], cfg) -> dict:
    return estimate_extraction_cost(chunks, cfg.extraction_model)

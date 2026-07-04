"""Ingestion pipeline orchestration.

Per book: extract text (read-only, staged copies) -> segment/chunk ->
LLM metadata -> embeddings -> upsert into ChromaDB + SQLite.

Change detection: every chunk's raw text is SHA-256 hashed and recorded in
{DATA_DIR}/chunk_hashes.json after a successful ingest. On the next run,
only chunks whose hash is new or different are re-extracted and re-embedded;
chunks that disappeared are deleted from both stores. A chunk whose metadata
extraction failed is deliberately NOT recorded, so the next run retries it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field

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
    if cfg.enable_note_ranking:
        sync_continuity_notes(records, embedder, store)

    failed_ids = [c.chunk_id for c, m in zip(chunks, metadata_list) if m is None]
    return {
        "chunks": len(chunks),
        "metadata_failed": len(failed_ids),
        "failed_chunk_ids": failed_ids,
        "api_calls": extractor.usage["api_calls"],
        "input_tokens": extractor.usage["input_tokens"],
        "output_tokens": extractor.usage["output_tokens"],
        "actual_cost_usd": extractor.actual_cost_usd,
    }


def sync_continuity_notes(records: list[dict], embedder, store) -> None:
    """Mirror changed chunks' foreshadowing/unresolved rows into the
    continuity-notes vector collection (only called when ENABLE_NOTE_RANKING
    is on). Delete-then-upsert per chunk so an edited chunk can't leave
    stale note vectors behind; local embeddings, so this costs nothing.
    Cheap by construction: it only ever sees the changed chunks."""
    from .notes import note_docs_for_chunk

    docs = []
    for r in records:
        docs.extend(note_docs_for_chunk(r["chunk"], r["metadata"] or {}))
    store.delete_notes_for_chunks([r["chunk"].chunk_id for r in records])
    if docs:
        embeddings = embedder.embed_documents([d["text"] for d in docs])
        for d, e in zip(docs, embeddings):
            d["embedding"] = e
        store.upsert_notes(docs)
    log.info("synced %d continuity note vector(s) for %d chunk(s)",
             len(docs), len(records))


def load_hash_index(cfg) -> dict[str, str]:
    """chunk_id -> sha256 of the chunk text, as of the last successful ingest."""
    if cfg.chunk_hashes_path.exists():
        try:
            return json.loads(cfg.chunk_hashes_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("chunk_hashes.json is corrupt — treating everything as new")
    return {}


def save_hash_index(cfg, index: dict[str, str]) -> None:
    cfg.ensure_data_dirs()
    cfg.chunk_hashes_path.write_text(
        json.dumps(index, indent=1, sort_keys=True), encoding="utf-8"
    )


@dataclass
class BookDiff:
    """What changed in one book since the last ingest."""
    new: list[Chunk] = field(default_factory=list)
    updated: list[Chunk] = field(default_factory=list)
    unchanged: list[Chunk] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)

    @property
    def changed(self) -> list[Chunk]:
        return self.new + self.updated


def diff_chunks(chunks: list[Chunk], index: dict[str, str],
                book_number: int) -> BookDiff:
    """Classify a book's current chunks against the stored hash index."""
    diff = BookDiff()
    current_ids = set()
    for c in chunks:
        current_ids.add(c.chunk_id)
        stored = index.get(c.chunk_id)
        if stored is None:
            diff.new.append(c)
        elif stored != chunk_text_hash(c):
            diff.updated.append(c)
        else:
            diff.unchanged.append(c)
    prefix = f"b{book_number:02d}."
    diff.deleted_ids = [cid for cid in index
                        if cid.startswith(prefix) and cid not in current_ids]
    return diff


def clear_staging(cfg) -> None:
    """Remove any leftover working copies (per source-protection rules)."""
    if cfg.staging_dir.exists():
        shutil.rmtree(cfg.staging_dir, ignore_errors=True)
    cfg.staging_dir.mkdir(parents=True, exist_ok=True)


def cost_estimate_for(chunks: list[Chunk], cfg) -> dict:
    return estimate_extraction_cost(chunks, cfg.extraction_model)

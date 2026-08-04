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


def reextract_chunks(cfg, chunks: list[Chunk], extractor: MetadataExtractor,
                     embedder, store) -> dict:
    """Metadata-only re-extraction (ingest.py --re-extract): re-runs the LLM
    extraction for `chunks` whose TEXT is unchanged, so parsing/chunking are
    reused from the caller and embeddings are fetched back from ChromaDB
    instead of being recomputed (identical text -> identical vectors). Only
    the side tables, chunk metadata, and continuity-note vectors update.

    Chunks whose extraction failed are NOT upserted — their existing (good)
    metadata stays in place; the caller drops them from the hash index so the
    next run retries them through the full path."""
    if not chunks:
        return {"chunks": 0}

    metadata_list = extractor.extract(chunks)
    embeddings = store.get_embeddings([c.chunk_id for c in chunks])
    missing = [c for c in chunks if c.chunk_id not in embeddings]
    if missing:  # e.g. a chunk that never made it into the store; embed fresh
        log.info("re-extract: embedding %d chunk(s) missing from ChromaDB",
                 len(missing))
        fresh = embedder.embed_documents([c.embedding_text for c in missing])
        embeddings.update({c.chunk_id: e for c, e in zip(missing, fresh)})

    records = [
        {"chunk": c, "metadata": m, "embedding": embeddings[c.chunk_id],
         "text_hash": chunk_text_hash(c)}
        for c, m in zip(chunks, metadata_list) if m is not None
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
    # Chunks whose PROSE is byte-identical to a chunk already in the index
    # under a different id — the same words, moved. Split out of `new` and
    # `updated` by detect_moved_chunks(); they are re-embedded and
    # re-upserted, never re-extracted. [(chunk, donor chunk_id)]
    moved: list[tuple[Chunk, str]] = field(default_factory=list)

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


def detect_moved_chunks(diff: BookDiff, index: dict[str, str],
                        book_number: int) -> None:
    """Split position-only changes out of `diff.new`/`diff.updated`, in place.

    The chunk id is positional — `b02.c040.s01.k00` — so inserting a chapter
    at 40 renumbers every chapter below it and every one of their chunks
    arrives under the id that used to belong to the chunk before it. Compared
    by ID that reads as "the entire tail of the book was rewritten", and the
    ingest pays the model to re-read prose it has already read. Faded is 94
    chapters and 368 chunks; an insert near the front rewrote ~215 of them.
    Compared by CONTENT it is what it actually is: the same words, moved.

    Note the shape this really takes. Almost nothing is `new` and nothing is
    `deleted` — an insert makes the book LONGER, so every old id still exists
    and simply holds its predecessor's prose. The tail lands in `updated`.
    That is why matching is against the whole stored index for the book
    rather than against `deleted_ids`: keying off deletions finds a
    *shortened* book (a chapter removed) and misses the common case entirely.

    A mover is paired with a *donor*: any stored chunk in the same book whose
    text hashes identically. Not a heuristic — donor prose and mover prose
    share a SHA-256, so the metadata being carried was extracted from exactly
    these words. One donor may serve several movers (a book can hold two
    byte-identical chunks); they are the same words, so they earn the same
    reading. Donor choice is deterministic (lowest id) so a re-run is stable.

    What legitimately differs is POSITION. Every positional field —
    chapter_number, chunk_index, heading, part — comes from the new chunk on
    write; only the model's reading of the prose is reused.
    """
    if not index:
        return
    prefix = f"b{book_number:02d}."
    donors: dict[str, str] = {}
    for cid, text_hash in index.items():
        if cid.startswith(prefix):
            current = donors.get(text_hash)
            if current is None or cid < current:
                donors[text_hash] = cid

    def sift(chunks: list[Chunk]) -> list[Chunk]:
        stays: list[Chunk] = []
        for c in chunks:
            donor = donors.get(chunk_text_hash(c))
            # A chunk sitting on its own id with its own hash is `unchanged`
            # and never reaches here; a donor equal to the chunk's own id
            # would therefore be a contradiction. Guard anyway — carrying a
            # chunk's metadata onto itself would skip a real re-extraction.
            if donor is not None and donor != c.chunk_id:
                diff.moved.append((c, donor))
            else:
                stays.append(c)
        return stays

    diff.new = sift(diff.new)
    diff.updated = sift(diff.updated)


def carry_chunks(cfg, moved: list[tuple[Chunk, str]], embedder, store) -> dict:
    """Re-home chunks that only moved: reuse the donor's LLM metadata, embed
    the prose locally, upsert under the new id. Zero API cost.

    Embeddings are NOT reused even though the prose is identical, because
    `embedding_text` folds in `context_prefix` — the tail of the preceding
    chunk — and an insert changes exactly that for the chunk after the seam.
    Re-embedding is a local model and costs nothing, so the correct vector is
    cheaper than the reasoning needed to decide when the stale one is safe.

    A donor whose metadata is missing (never extracted, or extraction failed
    and left NULL) is NOT carried — those chunks are returned in `refused` for
    the caller to run through the normal path, so a gap stays a gap rather
    than becoming a silently metadata-less chunk.
    """
    if not moved:
        return {"carried": 0, "refused": []}

    stored = store.get_metadata([donor for _, donor in moved])
    carried = [(c, stored[donor]) for c, donor in moved if donor in stored]
    refused = [c for c, donor in moved if donor not in stored]
    if not carried:
        return {"carried": 0, "refused": refused}

    embeddings = embedder.embed_documents([c.embedding_text for c, _ in carried])
    records = [
        {"chunk": c, "metadata": m, "embedding": e, "text_hash": chunk_text_hash(c)}
        for (c, m), e in zip(carried, embeddings)
    ]
    store.upsert_chunks(records)
    if cfg.enable_note_ranking:
        sync_continuity_notes(records, embedder, store)
    return {"carried": len(records), "refused": refused}


def clear_staging(cfg) -> None:
    """Remove any leftover working copies (per source-protection rules)."""
    if cfg.staging_dir.exists():
        shutil.rmtree(cfg.staging_dir, ignore_errors=True)
    cfg.staging_dir.mkdir(parents=True, exist_ok=True)


def cost_estimate_for(chunks: list[Chunk], cfg) -> dict:
    return estimate_extraction_cost(chunks, cfg.extraction_model)

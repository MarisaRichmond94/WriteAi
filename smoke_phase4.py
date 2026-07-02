"""Phase 4 smoke test: discovery + full ingestion of ONE book, then verify
both stores with a semantic query and a structured SQLite query.

Usage:
    .venv/bin/python smoke_phase4.py --book 1 [--yes]

Shows the cost estimate and asks for confirmation before any API calls
(unless --yes). Reads ~/Writing read-only; writes only under DATA_DIR.
"""

from __future__ import annotations

import argparse
import json
import sys

from config import load_config
from src.discovery import discover_books
from src.embedder import Embedder
from src.extractor import MetadataExtractor
from src.ingestion import (chunk_text_hash, clear_staging, cost_estimate_for,
                           ingest_chunks, load_and_chunk_book)
from src.storage import SeriesStore


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", type=int, default=1, help="book number to ingest")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    cfg = load_config()

    print("== discovery ==")
    books = discover_books(cfg)
    for b in books:
        print(f"  {b.number}. {b.title}  ->  {b.manuscript.name}")
    target = next((b for b in books if b.number == args.book), None)
    if target is None:
        print(f"book {args.book} not found")
        return 1

    print(f"\n== chunking book {target.number}: {target.title} ==")
    chunks = load_and_chunk_book(cfg, target)
    if chunks is None:
        return 1
    print(f"  {len(chunks)} chunks, {sum(c.word_count for c in chunks):,} words")

    est = cost_estimate_for(chunks, cfg)
    print("\n== cost estimate (metadata extraction) ==")
    for k, v in est.items():
        print(f"  {k}: {v}")
    print("  (embeddings are local — no API cost)")

    if not args.yes:
        if input("\nProceed? (yes/no): ").strip().lower() != "yes":
            print("aborted — no API calls made")
            return 0

    print("\n== loading embedding model ==")
    embedder = Embedder(cfg)
    store = SeriesStore(cfg)
    extractor = MetadataExtractor(cfg)

    print("== ingesting ==")
    store.delete_book(target.number)  # idempotent re-runs
    summary = ingest_chunks(cfg, chunks, extractor, embedder, store)
    clear_staging(cfg)
    print(json.dumps(summary, indent=2))

    print("\n== store counts ==")
    for k, v in store.counts().items():
        print(f"  {k}: {v}")

    print("\n== semantic search check ==")
    query = "the night Jared was forced to shoot his grandfather"
    hits = store.semantic_search(embedder.embed_query(query), top_k=3)
    print(f"  query: {query!r}")
    for h in hits:
        m = h["metadata"]
        print(f"  [{h['chunk_id']}] dist={h['distance']:.3f} "
              f"{m.get('book_title')} ch{m.get('chapter_number')} "
              f"(POV {m.get('pov_character')})")
        print(f"      {h['text'][:110]}…")

    print("\n== structured SQLite check ==")
    rows = store.chunks_with_character("Jensen")
    name = "Jensen"
    if not rows:  # fall back to a character we know exists
        name = "Jared"
        rows = store.chunks_with_character(name)
    chapters = sorted({(r["book_number"], r["chapter_number"]) for r in rows})
    print(f"  chunks where '{name}' is present: {len(rows)} "
          f"across {len(chapters)} chapters")
    return 0


if __name__ == "__main__":
    sys.exit(main())

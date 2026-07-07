"""Build the book-scoped location gazetteer (location_map_v2) — standalone CLI.

Thin wrapper around src/location_resolve.py (per-book batched structured-output
calls to EXTRACTION_MODEL, upserting (book, raw) -> place/parent/area; see that
module's docstring for why v1's series-wide map corrupted moving characters'
homes). Re-running is safe: rows are upserted in place and books whose raw
strings have not changed are skipped via enrich_state. The enrichment flow
(server/enrich.py) re-resolves affected books automatically after a resync
when ENABLE_LOCATION_V2 is on; this script remains the way to (re)build the
whole series in one go.

Usage (from the repo root):
    .venv/bin/python scripts/resolve_locations.py --dry-run   # plan, no API
    .venv/bin/python scripts/resolve_locations.py             # resolve + upsert
    .venv/bin/python scripts/resolve_locations.py --force     # ignore state
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import load_config
from src.location_resolve import (BATCH_SIZE, book_inputs, ensure_table,
                                  pending_books, resolve_locations)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Resolve the book-scoped location gazetteer")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan (books, raw-string counts, batches) "
                         "without any API calls or writes")
    ap.add_argument("--force", action="store_true",
                    help="re-resolve every book even if its inputs are "
                         "unchanged since the last run")
    args = ap.parse_args()

    cfg = load_config()
    db = sqlite3.connect(cfg.sqlite_path)
    ensure_table(db)
    if args.force:
        db.execute("DELETE FROM enrich_state WHERE scope LIKE 'locmap_v2:%'")
        db.commit()
    todo = pending_books(db)
    every = book_inputs(db)

    print(f"{'book':>5}  {'raw strings':>11}  {'batches':>7}  status")
    for book, raws in sorted(every.items()):
        n_batches = math.ceil(len(raws) / BATCH_SIZE)
        status = "pending" if book in todo else "up to date"
        print(f"{book:>5}  {len(raws):>11}  {n_batches:>7}  {status}")
    if args.dry_run:
        print("\nDry run — no API calls made. (The backfill and region "
              "passes run with the real thing even when every book is up "
              "to date; they keep their own state.)")
        return 0

    import anthropic
    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key or None,
                                 max_retries=4)

    def on_batch(book: int, n: int) -> None:
        print(f"  book {book}: batch written ({n} mappings)")

    stats: dict = {}
    resolve_locations(db, cfg, client, on_batch=on_batch, stats=stats)
    print(f"\nresolved books: {stats['books_resolved'] or 'none'}"
          f"  rows upserted: {stats['upserts']}"
          f"  backfilled: {stats.get('backfilled', 0)}"
          f"  venue parents: {stats.get('parent_updates', 0)}"
          f"  region updates: {stats.get('region_updates', 0)}"
          f"  failed batches: {stats['failed_batches']}"
          f"  cost: ${stats['cost_usd']:.4f}")
    return 1 if stats["failed_batches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

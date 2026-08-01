"""Stamp loom_chapter_id onto existing chapter_summaries rows (LOOM-65).

The column is written on every enrichment from now on, but existing rows
predate it. Until they carry an id the read path falls back to matching by
chapter number, which is the staleness LOOM-65 exists to remove — so without
this the fix only reaches a chapter once it is next re-enriched, and
enrichment is cost-gated and on a cadence.

The mapping is (book_number, chapter_number) -> the manifest's chapter cuid at
the CURRENT numbering. That is only sound while the index and the manifest
agree about numbering: mid-drift, a row's number points at a chapter that is
about to become a different one, and stamping then would weld today's stale
pairing into an id that outlives it. So every book is checked first and a
drifting book is skipped, not guessed at — it will be picked up on a later run
once its ingest has caught up.

Idempotent: rows that already carry an id are left alone, so re-running is a
no-op. Dry by default.

    .venv/bin/python scripts/backfill_chapter_ids.py            # report only
    .venv/bin/python scripts/backfill_chapter_ids.py --apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config                      # noqa: E402
from src.discovery import discover_books, read_manifest_chapters  # noqa: E402


def indexed_chapters(db, book) -> set[int]:
    """Chapter numbers the index holds — the same preference order as
    `sync._indexed_chapters`, so this agrees with the app's own drift check."""
    if book.loom_book_id:
        rows = {r[0] for r in db.execute(
            "SELECT DISTINCT chapter_number FROM chunks WHERE loom_book_id = ?",
            (book.loom_book_id,))}
        if rows:
            return rows
    return {r[0] for r in db.execute(
        "SELECT DISTINCT chapter_number FROM chunks WHERE book_number = ?",
        (book.number,))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default: report only)")
    args = ap.parse_args()

    cfg = load_config()
    db = sqlite3.connect(cfg.sqlite_path)
    cols = {r[1] for r in db.execute(
        "SELECT * FROM pragma_table_info('chapter_summaries')")}
    if "loom_chapter_id" not in cols:
        print("chapter_summaries has no loom_chapter_id column — start the "
              "server once to run migrate_schema, then re-run this.")
        return 1

    total_stamped = total_skipped = 0
    for book in discover_books(cfg):
        chapters = read_manifest_chapters(book.folder, book.title)
        num_to_id = {c["number"]: c["id"] for c in chapters}
        rows = db.execute(
            "SELECT chapter_number, loom_chapter_id FROM chapter_summaries "
            "WHERE book_number = ?", (book.number,)).fetchall()
        if not rows:
            continue

        if not num_to_id:
            print(f"book {book.number} ({book.title}): no readable manifest — "
                  f"skipped, {len(rows)} row(s) keep number matching")
            total_skipped += len(rows)
            continue

        # Drift guard. Compare against canon chapters that HAVE PROSE: a stub
        # produces no chunks and can never be indexed, so demanding equality
        # against all of canon would skip every book that has one.
        written = {c["number"] for c in chapters if c.get("wordCount")}
        if written != indexed_chapters(db, book):
            print(f"book {book.number} ({book.title}): index and manifest "
                  f"disagree about numbering — SKIPPED. Re-run after its next "
                  f"ingest.")
            total_skipped += len(rows)
            continue

        pending = [(n, cid) for n, cid in rows if not cid]
        unresolved = [n for n, _ in pending if n not in num_to_id]
        stampable = [(n, num_to_id[n]) for n, _ in pending if n in num_to_id]

        print(f"book {book.number} ({book.title}): {len(rows)} row(s), "
              f"{len(rows) - len(pending)} already stamped, "
              f"{len(stampable)} to stamp"
              + (f", {len(unresolved)} with no matching canon chapter "
                 f"{unresolved[:5]}" if unresolved else ""))

        if args.apply and stampable:
            db.executemany(
                "UPDATE chapter_summaries SET loom_chapter_id = ? "
                "WHERE book_number = ? AND chapter_number = ? "
                "AND loom_chapter_id IS NULL",
                [(cid, book.number, n) for n, cid in stampable])
            db.commit()
        total_stamped += len(stampable)
        total_skipped += len(unresolved)

    verb = "stamped" if args.apply else "would stamp"
    print(f"\n{verb} {total_stamped} row(s); {total_skipped} left on number "
          f"matching.")
    if not args.apply:
        print("Dry run — nothing was written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

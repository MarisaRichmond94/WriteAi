"""One-time backfill of events.loom_chapter_id from chapter_summaries.

RUN ONCE, AND ONLY WHILE THE NUMBERING IS STILL TRUE. This joins the two
enrichment tables positionally, on (book_number, chapter_number), which is
valid only because every existing row in both was written under the same
numbering. After a chapter is inserted, a NULL-id events row and the summary
row at its number describe DIFFERENT chapters, and this script would stamp
the wrong identity onto it permanently. That is precisely why the codebase
stamps identity on write everywhere else and distrusts backfills.

It exists because `events` gained loom_chapter_id after 1015 rows already
existed, and there is no path by which they would acquire it on their own:
enrich_state is keyed by chapter cuid, so a chapter whose prose has not
changed is never re-enriched, so its events are never rewritten. Without this
those rows stay unidentifiable forever, and
`reposition_renumbered_chapters` can never move them — the exact staleness
it was written to prevent.

Idempotent (only touches NULLs) but that is a safety net, not a licence to
re-run it later.

    .venv/bin/python scripts/backfill_event_chapter_ids.py [--dry-run]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config  # noqa: E402


def main() -> int:
    dry = "--dry-run" in sys.argv
    cfg = load_config()
    db = sqlite3.connect(cfg.sqlite_path)
    db.execute("PRAGMA busy_timeout = 30000")

    total, missing = db.execute(
        "SELECT COUNT(*), SUM(loom_chapter_id IS NULL) FROM events").fetchone()
    print(f"events: {missing or 0} of {total} without a chapter id")
    if not missing:
        print("nothing to do.")
        return 0

    resolvable = db.execute(
        """SELECT COUNT(*) FROM events e WHERE e.loom_chapter_id IS NULL
           AND EXISTS (SELECT 1 FROM chapter_summaries s
                       WHERE s.book_number = e.book_number
                         AND s.chapter_number = e.chapter_number
                         AND s.loom_chapter_id IS NOT NULL)""").fetchone()[0]
    print(f"resolvable from chapter_summaries: {resolvable}")
    print(f"left NULL (no identified summary at that number): {missing - resolvable}")

    if dry:
        print("\n--dry-run: no writes.")
        return 0

    # Snapshot first, via the project's own backup path — cp on a live SQLite
    # file silently drops the WAL and yields a stale copy.
    from scripts.backup_index import snapshot
    dest = snapshot(cfg, "pre-event-id-backfill", quiet=True)
    print(f"\nindex backed up -> {dest.name}")

    n = db.execute(
        """UPDATE events SET loom_chapter_id = (
               SELECT s.loom_chapter_id FROM chapter_summaries s
               WHERE s.book_number = events.book_number
                 AND s.chapter_number = events.chapter_number)
           WHERE loom_chapter_id IS NULL
             AND EXISTS (SELECT 1 FROM chapter_summaries s
                         WHERE s.book_number = events.book_number
                           AND s.chapter_number = events.chapter_number
                           AND s.loom_chapter_id IS NOT NULL)""").rowcount
    db.commit()
    print(f"stamped {n} event row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

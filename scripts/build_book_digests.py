"""Manually rebuild the condensed per-book story digests.

You should not normally need this: the enrichment run — the only pipeline
that rewrites chapter summaries — ends by refreshing stale digests itself
(server/enrich.py), and the read path falls back to the full bible whenever
a digest is missing or stale. This script is the recovery/backfill tool,
mirroring scripts/resolve_chronology.py: first-time backfill on an existing
store, retrying after a failed refresh, or clearing digests to revert
review/chat to full bibles.

Usage:
    .venv/bin/python scripts/build_book_digests.py            # build/refresh stale
    .venv/bin/python scripts/build_book_digests.py --force    # rebuild everything
    .venv/bin/python scripts/build_book_digests.py --clear    # delete all digests
                                                              # (instant revert to
                                                              # full bibles)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.deps import get_state                                # noqa: E402
from server.digests import (DIGESTS_DDL, digest_source,          # noqa: E402
                            refresh_digests)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true",
                    help="rebuild digests even when fresh")
    ap.add_argument("--clear", action="store_true",
                    help="delete all stored digests and exit")
    args = ap.parse_args()

    s = get_state()
    db = s.db
    db.execute(DIGESTS_DDL)
    db.commit()

    if args.clear:
        n = db.execute("SELECT COUNT(*) FROM book_digests").fetchone()[0]
        db.execute("DELETE FROM book_digests")
        db.commit()
        print(f"cleared {n} digest(s) — review/chat fall back to full bibles")
        return 0

    import anthropic
    client = anthropic.Anthropic(api_key=s.cfg.anthropic_api_key or None,
                                 max_retries=3)
    books = [r[0] for r in db.execute(
        "SELECT DISTINCT book_number FROM chunks ORDER BY book_number")]
    stats = refresh_digests(db, s.cfg, client, books,
                            source_for=lambda b: digest_source(s, b),
                            force=args.force,
                            on_book=lambda b: print(f"  book {b} checked"))
    print(f"\n{stats['built']} rebuilt, {stats['skipped']} fresh, "
          f"{stats['failed']} failed — spend ${stats['cost_usd']:.4f}")
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())

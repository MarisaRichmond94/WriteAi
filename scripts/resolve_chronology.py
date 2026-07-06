"""Assign story_year/temporal_mode to every chapter — standalone CLI.

Thin wrapper around src/chronology.py (per-book structured-output call to
EXTRACTION_MODEL + deterministic verify-and-repair + upsert into
chapter_timeline; see that module's docstring for the full story). Re-running
is safe: rows are upserted in place and manual_override=1 rows are never
touched. The enrichment flow (server/enrich.py) re-resolves affected books
automatically after a resync when ENABLE_STORY_ORDER is on; this script
remains the way to (re)build the whole series in one go.

Usage (from the repo root):
    .venv/bin/python scripts/resolve_chronology.py --dry-run   # plan, no API
    .venv/bin/python scripts/resolve_chronology.py             # resolve + upsert
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import load_config
from src.chronology import chapter_inputs, ensure_table, resolve_chronology


def print_book_table(book: int, chapters: list[dict],
                     assigned: dict[int, dict] | None) -> None:
    print(f"\n── Book {book} "
          + ("(resolved)" if assigned else "(plan — no story_year yet)")
          + " " + "─" * 40)
    hdr = f"{'ch':>4}  {'date_line':<28} {'m/d':<6}"
    if assigned:
        hdr += f" {'year':>4}  {'mode':<12} {'conf':>4}"
    print(hdr)
    for c in chapters:
        md = (f"{c['month']}/{c['day']}"
              if c["month"] and c["day"] else "—")
        line = f"{c['chapter_number']:>4}  {(c['date_line'] or '—'):<28} {md:<6}"
        if assigned:
            a = assigned.get(c["chapter_number"])
            if a:
                line += (f" {a['story_year']:>4}  {a['temporal_mode']:<12}"
                         f" {a['confidence']:>4.2f}")
            else:
                line += "   (missing from model output)"
        print(line)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Assign story_year/temporal_mode to every chapter")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan (chapters, parsed dates, prompt "
                         "inputs) without any API calls or writes")
    args = ap.parse_args()

    cfg = load_config()
    db = sqlite3.connect(cfg.sqlite_path)
    ensure_table(db)
    books = chapter_inputs(db)
    if not books:
        print("no chapters found — ingest first")
        return 1

    overridden = {(b, c) for b, c in db.execute(
        "SELECT book_number, chapter_number FROM chapter_timeline "
        "WHERE manual_override = 1")}
    if overridden:
        print(f"respecting {len(overridden)} manual override(s); "
              "those rows will not be rewritten")

    if args.dry_run:
        for book in sorted(books):
            print_book_table(book, books[book], assigned=None)
        n = sum(len(v) for v in books.values())
        print(f"\ndry run: {n} chapters across {len(books)} book(s); "
              f"{len(books)} {cfg.extraction_model} call(s) would be made.")
        return 0

    import anthropic
    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key or None,
                                 max_retries=4)

    def on_book(book: int, chapters: list[dict], assigned: dict[int, dict],
                n_fixed: int, kind: str) -> None:
        if n_fixed:
            print(f"book {book}: calendar consistency repair adjusted "
                  f"{n_fixed} chapter(s) (see rationale notes)")
        print_book_table(book, chapters, assigned)

    stats: dict = {}
    try:
        resolve_chronology(db, cfg, client, on_book=on_book, stats=stats)
    finally:
        usage = stats.get("usage",
                          {"api_calls": 0, "input_tokens": 0, "output_tokens": 0})
        print(f"\n{usage['api_calls']} API call(s), "
              f"{usage['input_tokens']} in / {usage['output_tokens']} out "
              f"tokens — ${stats.get('cost_usd', 0.0):.4f}; "
              f"{stats.get('upserts', 0)} chapter rows upserted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

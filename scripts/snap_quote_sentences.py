"""One-time pass: snap every stored source_quote to sentence boundaries.

Extraction-time source_quotes were verified as verbatim substrings of their
chunk text but not sentence-aligned (the model often starts/stops
mid-sentence). This script rewrites every stored quote through the SAME
snapping logic the extractor now applies at parse time
(src/quotesnap.snap_quote_to_sentences), so old and new quotes read alike.

Quotes live in four places, all updated here:
  * foreshadowing.source_quote            (SQLite side table)
  * unresolved_questions.source_quote     (SQLite side table)
  * character_knowledge.source_quote      (SQLite side table)
  * chunks.metadata_json quote lists      (emotional_beat_quotes,
    foreshadowing_quotes, unresolved_question_quotes, and the
    character_knowledge_quotes dict) — the extractor's full output, which the
    side tables mirror (see src/storage.py).

The SQLite file is backed up to <db>.pre-snap-backup first (skipped when the
backup already exists). Quotes that cannot be located in their chunk's text
(should be ~none — they were verified at parse time against the same text)
are counted and left unchanged.

IMPORTANT downstream step: note docs in the Chroma notes collection embed the
quote text and fold it into their ids (src/notes.py), so after this script
you MUST re-run scripts/backfill_note_embeddings.py — it re-upserts the new
ids and prunes the stale ones.

Usage (from the repo root):
    .venv/bin/python scripts/snap_quote_sentences.py
    .venv/bin/python scripts/snap_quote_sentences.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import load_config
from src.quotesnap import locate_quote, snap_quote_to_sentences

# (table, value column) for every side table carrying a source_quote.
_TABLES = (("foreshadowing", "detail"),
           ("unresolved_questions", "question"),
           ("character_knowledge", "learns"))

# Parallel quote lists inside chunks.metadata_json (see extractor._merge).
_META_LIST_KEYS = ("emotional_beat_quotes", "foreshadowing_quotes",
                   "unresolved_question_quotes")
_META_DICT_KEY = "character_knowledge_quotes"  # {character: [quote|None, ...]}


class Snapper:
    def __init__(self, chunk_texts: dict[str, str]):
        self.texts = chunk_texts
        self.examined = 0
        self.snapped = 0
        self.unlocatable = 0
        self.examples: list[tuple[str, str, str]] = []  # (where, before, after)

    def snap(self, quote: str, chunk_id: str, where: str) -> str:
        """Snapped quote (or the original, unchanged, when unlocatable or
        already aligned), with tallies and mid-sentence examples collected."""
        self.examined += 1
        text = self.texts.get(chunk_id, "")
        if locate_quote(quote, text) is None:
            self.unlocatable += 1
            return quote
        snapped = snap_quote_to_sentences(quote, text)
        if snapped != quote:
            self.snapped += 1
            first = next((c for c in quote if c.isalpha()), "")
            if first.islower() and len(self.examples) < 12:
                self.examples.append((where, quote, snapped))
        return snapped


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Snap all stored source_quotes to sentence boundaries")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args()

    cfg = load_config()
    db_path = Path(cfg.sqlite_path)
    if not db_path.exists():
        print(f"no database at {db_path} — run ingest.py first")
        return 1

    backup = db_path.with_name(db_path.name + ".pre-snap-backup")
    if backup.exists():
        print(f"backup already exists (skipping): {backup}")
    elif args.dry_run:
        print(f"dry run: would back up to {backup}")
    else:
        shutil.copy2(db_path, backup)
        print(f"backed up {db_path} -> {backup}")

    db = sqlite3.connect(db_path)
    snapper = Snapper(dict(db.execute("SELECT chunk_id, text FROM chunks")))

    # ── SQLite side tables ───────────────────────────────────────────────────
    for table, _column in _TABLES:
        updates = []
        rows = db.execute(
            f"SELECT rowid, chunk_id, source_quote FROM {table} "
            f"WHERE source_quote IS NOT NULL").fetchall()
        for rowid, chunk_id, quote in rows:
            snapped = snapper.snap(quote, chunk_id, table)
            if snapped != quote:
                updates.append((snapped, rowid))
        if updates and not args.dry_run:
            db.executemany(
                f"UPDATE {table} SET source_quote = ? WHERE rowid = ?", updates)
        print(f"{table}: {len(rows)} quotes examined, {len(updates)} snapped")

    # ── chunks.metadata_json quote lists ────────────────────────────────────
    meta_examined_before = snapper.examined
    meta_updates = []
    for chunk_id, raw in db.execute(
            "SELECT chunk_id, metadata_json FROM chunks "
            "WHERE metadata_json IS NOT NULL"):
        meta = json.loads(raw)
        changed = False
        for key in _META_LIST_KEYS:
            quotes = meta.get(key)
            if not quotes:
                continue
            for i, q in enumerate(quotes):
                if q is None:
                    continue
                snapped = snapper.snap(q, chunk_id, f"metadata:{key}")
                if snapped != q:
                    quotes[i] = snapped
                    changed = True
        for quotes in (meta.get(_META_DICT_KEY) or {}).values():
            for i, q in enumerate(quotes):
                if q is None:
                    continue
                snapped = snapper.snap(q, chunk_id,
                                       f"metadata:{_META_DICT_KEY}")
                if snapped != q:
                    quotes[i] = snapped
                    changed = True
        if changed:
            meta_updates.append((json.dumps(meta, ensure_ascii=False), chunk_id))
    if meta_updates and not args.dry_run:
        db.executemany(
            "UPDATE chunks SET metadata_json = ? WHERE chunk_id = ?",
            meta_updates)
    print(f"metadata_json: {snapper.examined - meta_examined_before} quotes "
          f"examined, {len(meta_updates)} chunk row(s) updated")

    if not args.dry_run:
        db.commit()
    db.close()

    print(f"\nTOTAL: {snapper.examined} examined / {snapper.snapped} snapped "
          f"/ {snapper.unlocatable} unlocatable (left unchanged)"
          + (" [dry run — nothing written]" if args.dry_run else ""))

    if snapper.examples:
        print("\nExamples (quotes that started mid-sentence):")
        for where, before, after in snapper.examples[:8]:
            print(f"\n  [{where}]")
            print(f"    before: {before}")
            print(f"    after:  {after}")

    print("\nNEXT: re-run scripts/backfill_note_embeddings.py — note-doc ids "
          "fold in the quote text, so the notes collection must be rebuilt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

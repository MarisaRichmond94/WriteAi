"""Backfill the continuity-notes vector collection from SQLite.

Reads every foreshadowing + unresolved_questions row, renders each as the
exact note line the retriever injects (src/notes.py — shared, so the two
can never drift), embeds them with the configured embedder (local by
default: no API cost), and upserts them into the `{collection}-notes`
Chroma collection used by ENABLE_NOTE_RANKING.

Idempotent: doc ids are deterministic (kind + chunk_id + text hash), so
re-running upserts in place; vectors whose source rows no longer exist are
pruned at the end. Safe to re-run at any time. The main chunks collection
is never touched.

Usage (from the repo root):
    .venv/bin/python scripts/backfill_note_embeddings.py
    .venv/bin/python scripts/backfill_note_embeddings.py --batch 512
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import load_config
from src.notes import note_docs_from_db


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Embed all continuity notes into the notes collection")
    ap.add_argument("--batch", type=int, default=256,
                    help="notes embedded/upserted per batch (default 256)")
    args = ap.parse_args()

    cfg = load_config()

    # Heavy imports after config so the log level is set (mirrors query.py).
    from src.embedder import Embedder
    from src.storage import SeriesStore

    store = SeriesStore(cfg)
    counts = store.counts()
    n_rows = counts["foreshadowing"] + counts["unresolved_questions"]
    docs = note_docs_from_db(store.db)
    if not docs:
        print("No foreshadowing/unresolved rows found — run ingest.py first.")
        return 1
    dupes = n_rows - len(docs)
    print(f"{n_rows} note rows in SQLite "
          f"({counts['foreshadowing']} foreshadowing + "
          f"{counts['unresolved_questions']} unresolved) -> "
          f"{len(docs)} unique note docs"
          + (f" ({dupes} duplicate row(s) collapsed)" if dupes else ""))

    embedder = Embedder(cfg)
    t0 = time.time()
    for i in range(0, len(docs), args.batch):
        batch = docs[i:i + args.batch]
        embeddings = embedder.embed_documents([d["text"] for d in batch])
        for d, e in zip(batch, embeddings):
            d["embedding"] = e
        store.upsert_notes(batch)
        print(f"  {min(i + args.batch, len(docs))}/{len(docs)} notes "
              f"embedded + upserted ({time.time() - t0:.0f}s elapsed)",
              flush=True)

    # Prune vectors whose source row was edited/removed since the last run.
    existing = set(store.notes.get(include=[])["ids"])
    stale = sorted(existing - {d["id"] for d in docs})
    if stale:
        store.notes.delete(ids=stale)
        print(f"pruned {len(stale)} stale note vector(s)")

    final = store.notes_count()
    status = "OK" if final == len(docs) else "MISMATCH"
    print(f"done in {time.time() - t0:.1f}s: notes collection has {final} "
          f"vectors (expected {len(docs)}) — {status}")
    return 0 if final == len(docs) else 1


if __name__ == "__main__":
    sys.exit(main())

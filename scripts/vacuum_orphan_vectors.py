#!/usr/bin/env python3
"""Vacuum orphaned vectors from the ChromaDB chunk collection.

An *orphan* is a vector whose chunk_id no longer exists in the metadata
`chunks` table — left behind when a re-ingest deleted/renumbered chunks but the
matching vector delete never completed (e.g. under the old SQLite lock
contention). Orphans resolve to null metadata at query time and used to crash
the retriever; they're stale content that should not be searchable.

Run this with the WriteAI server STOPPED — ChromaDB is not safe with two
processes writing the same path. Dry-run by default; pass --apply to snapshot
then delete.

    python scripts/vacuum_orphan_vectors.py            # report only
    python scripts/vacuum_orphan_vectors.py --apply    # snapshot + delete
"""
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def main(apply: bool) -> int:
    from config import load_config
    cfg = load_config()
    from src.storage import SeriesStore

    store = SeriesStore(cfg)
    vec_ids = set(store.collection.get(include=[])["ids"])
    db_ids = {r[0] for r in
              sqlite3.connect(cfg.sqlite_path).execute("SELECT chunk_id FROM chunks")}
    orphans = sorted(vec_ids - db_ids)
    missing = sorted(db_ids - vec_ids)  # reverse gap: chunks with no vector (report only)

    print(f"vectors={len(vec_ids)}  chunks={len(db_ids)}  "
          f"orphans={len(orphans)}  chunks_without_vector={len(missing)}")
    if orphans:
        print("  orphan sample:", orphans[:10])
    if missing:
        print("  missing-vector sample:", missing[:10])

    if not orphans:
        print("nothing to vacuum.")
        return 0
    if not apply:
        print("DRY-RUN — re-run with --apply to snapshot + delete.")
        return 0

    subprocess.run([sys.executable, "scripts/backup_index.py",
                    "snapshot", "--label", "pre-orphan-vacuum"], check=True)
    store.collection.delete(ids=orphans)
    remaining = set(store.collection.get(include=[])["ids"]) - db_ids
    print(f"deleted {len(orphans)} orphan vectors. collection now "
          f"{store.collection.count()}. remaining orphans: {len(remaining)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))

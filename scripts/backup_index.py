"""Snapshot / restore the entire search index so a reindex is reversible.

`ingest.py` mutates the index **in place** across three stores that reference
each other by chunk_id, with no transaction spanning them:

  * data/chroma_db/              — the vector store (Chroma: sqlite + HNSW segments)
  * data/series_metadata.sqlite  — chunks, FTS5 keyword index, side + enrichment tables
  * data/chunk_hashes.json       — the change-detection ledger the next diff reads

If a run crashes or produces a bad index, these can end up inconsistent. This
tool copies all three (plus the small rich_text UI sidecars) into
data/backups/<timestamp>/ as one set, and restores them together.

The extracted_text/ cache is deliberately NOT snapshotted: it is content-
addressed by source-file hash and a reindex only appends to it, so the old
chunks' extracted text is still present after any reindex — restoring the three
core stores is enough, and skipping the cache roughly halves snapshot size.

Usage (from the repo root):
    .venv/bin/python scripts/backup_index.py snapshot                # back up now
    .venv/bin/python scripts/backup_index.py snapshot --label pre-full-reindex
    .venv/bin/python scripts/backup_index.py list                    # show snapshots
    .venv/bin/python scripts/backup_index.py prune                   # keep newest 5
    .venv/bin/python scripts/backup_index.py restore <name>          # roll back
    .venv/bin/python scripts/backup_index.py restore latest --yes

Only the newest MAX_BACKUPS (5) snapshots are kept: `snapshot` prunes older
ones after each run, and `ingest.py` takes an automatic `pre-ingest` snapshot
before every reindex (skip with `ingest.py --no-backup`).

restore first takes an automatic `pre-restore-<ts>` snapshot of the current
state, so a restore is itself reversible. After restoring while the server is
running, restart it (or hit the rebuild button) so it reloads the swapped-in
Chroma segments — the live process still holds the old ones in memory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import load_config

MANIFEST_NAME = "manifest.json"
MAX_BACKUPS = 5  # snapshots kept after pruning; older ones are deleted


def _index_paths(cfg) -> list[tuple[str, Path]]:
    """(label, path) for every piece backed up to make a consistent index state.

    The first three are the destructive-upsert core that ingest.py rewrites in
    place; rich_text is a small rebuildable UI sidecar included so the snapshot
    is a complete point-in-time copy. extracted_text/ is intentionally omitted
    (content-addressed, append-only cache — see the module docstring), and
    staging_dir is transient.
    """
    return [
        ("chroma_db", Path(cfg.chroma_dir)),
        ("series_metadata.sqlite", Path(cfg.sqlite_path)),
        ("chunk_hashes.json", Path(cfg.chunk_hashes_path)),
        ("rich_text", Path(cfg.rich_text_dir)),
    ]


def _du(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _human(n: int) -> str:
    x = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if x < 1024 or unit == "GB":
            return f"{x:.1f}{unit}" if unit != "B" else f"{int(x)}B"
        x /= 1024
    return f"{x:.1f}GB"


def _backups_dir(cfg) -> Path:
    return Path(cfg.data_dir) / "backups"


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def snapshot(cfg, label: str | None, *, quiet: bool = False) -> Path:
    """Copy the current index set into data/backups/<ts>[_label]/. Returns the dir."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{ts}_{label}" if label else ts
    dest = _backups_dir(cfg) / name
    if dest.exists():
        raise SystemExit(f"snapshot dir already exists: {dest}")

    entries: list[dict] = []
    for key, path in _index_paths(cfg):
        if not path.exists():
            if not quiet:
                print(f"  skip   {key}  (not present)")
            continue
        size = _du(path)
        _copy(path, dest / path.name)
        entries.append({"key": key, "name": path.name,
                        "is_dir": path.is_dir(), "bytes": size})
        if not quiet:
            print(f"  copied {key}  ({_human(size)})")

    if not any(e["key"] in ("chroma_db", "series_metadata.sqlite") for e in entries):
        shutil.rmtree(dest, ignore_errors=True)
        raise SystemExit("no index found to back up — run ingest.py first")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "data_dir": str(Path(cfg.data_dir).resolve()),
        "series_name": cfg.series_name,
        "entries": entries,
        "total_bytes": sum(e["bytes"] for e in entries),
    }
    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    if not quiet:
        print(f"\nsnapshot -> {dest}  ({_human(manifest['total_bytes'])})")
    return dest


def _snapshots(cfg) -> list[Path]:
    root = _backups_dir(cfg)
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir()
                   if p.is_dir() and (p / MANIFEST_NAME).exists()),
                  key=lambda p: p.name)


def list_snapshots(cfg) -> int:
    snaps = _snapshots(cfg)
    if not snaps:
        print(f"no snapshots in {_backups_dir(cfg)}")
        return 0
    print(f"snapshots in {_backups_dir(cfg)}:\n")
    for p in snaps:
        m = json.loads((p / MANIFEST_NAME).read_text())
        keys = ", ".join(e["key"] for e in m["entries"])
        print(f"  {p.name}")
        print(f"      {m['created_utc']}  {_human(m['total_bytes'])}  [{keys}]")
    print(f"\nrestore with:  scripts/backup_index.py restore {snaps[-1].name}")
    return 0


def prune(cfg, keep: int = MAX_BACKUPS, protect: tuple[Path, ...] = (),
          *, quiet: bool = False) -> list[Path]:
    """Delete the oldest snapshots beyond `keep`. Returns the dirs removed.

    Snapshot dir names are timestamp-prefixed, so lexical order == chronological.
    Anything in `protect` is never deleted (used by restore to shield the very
    snapshot it is restoring from), and stays even if that leaves > keep.
    """
    protected = {p.resolve() for p in protect}
    snaps = _snapshots(cfg)  # oldest -> newest
    removable = [p for p in snaps if p.resolve() not in protected]
    excess = max(0, len(snaps) - keep)
    removed: list[Path] = []
    for p in removable[:excess]:
        shutil.rmtree(p)
        removed.append(p)
        if not quiet:
            print(f"  pruned {p.name}")
    return removed


def _resolve(cfg, name: str) -> Path:
    snaps = _snapshots(cfg)
    if not snaps:
        raise SystemExit("no snapshots to restore")
    if name in ("latest", "last"):
        return snaps[-1]
    exact = _backups_dir(cfg) / name
    if exact.is_dir():
        return exact
    matches = [p for p in snaps if p.name.startswith(name)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"no snapshot matching {name!r}")
    raise SystemExit("ambiguous name; matches: " + ", ".join(p.name for p in matches))


def restore(cfg, name: str, *, assume_yes: bool) -> int:
    src = _resolve(cfg, name)
    manifest = json.loads((src / MANIFEST_NAME).read_text())
    print(f"restore from: {src}")
    print(f"  created {manifest['created_utc']}  ({_human(manifest['total_bytes'])})")
    for e in manifest["entries"]:
        print(f"  - {e['key']}  ({_human(e['bytes'])})")

    if not assume_yes:
        reply = input("\nThis overwrites the live index. Continue? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.")
            return 1

    print("\ntaking a safety snapshot of the current state first...")
    snapshot(cfg, "pre-restore", quiet=True)

    for e in manifest["entries"]:
        backed = src / e["name"]
        live = Path(cfg.data_dir) / e["name"]
        cfg.assert_never_inside_books_dir(live)
        if not backed.exists():
            print(f"  WARN missing in snapshot, skipping: {e['name']}")
            continue
        # Swap in via a temp sibling so a mid-copy crash can't leave a half dir.
        tmp = live.with_name(live.name + ".restoring")
        if tmp.exists():
            shutil.rmtree(tmp) if tmp.is_dir() else tmp.unlink()
        _copy(backed, tmp)
        if live.exists():
            shutil.rmtree(live) if live.is_dir() else live.unlink()
        tmp.rename(live)
        print(f"  restored {e['key']}")

    # Keep the backup set bounded, but never delete the snapshot we just
    # restored from — it's still the user's chosen rollback point.
    prune(cfg, protect=(src,), quiet=True)

    print("\ndone. If the server is running, restart it (or hit rebuild) so it "
          "reloads the restored Chroma segments.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Snapshot / restore the search index.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("snapshot", help="back up the current index")
    ps.add_argument("--label", help="suffix for the snapshot dir name")
    ps.add_argument("--keep", type=int, default=MAX_BACKUPS,
                    help=f"snapshots to keep after this one (default {MAX_BACKUPS})")

    sub.add_parser("list", help="list snapshots")

    pp = sub.add_parser("prune", help=f"delete all but the newest N snapshots")
    pp.add_argument("--keep", type=int, default=MAX_BACKUPS,
                    help=f"snapshots to keep (default {MAX_BACKUPS})")

    pr = sub.add_parser("restore", help="restore a snapshot (rolls the index back)")
    pr.add_argument("name", help="snapshot dir name (or a unique prefix, or 'latest')")
    pr.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    args = ap.parse_args()
    cfg = load_config()

    if args.cmd == "snapshot":
        snapshot(cfg, args.label)
        prune(cfg, keep=args.keep)
        return 0
    if args.cmd == "list":
        return list_snapshots(cfg)
    if args.cmd == "prune":
        removed = prune(cfg, keep=args.keep)
        print(f"pruned {len(removed)} snapshot(s); "
              f"{len(_snapshots(cfg))} remaining")
        return 0
    if args.cmd == "restore":
        return restore(cfg, args.name, assume_yes=args.yes)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

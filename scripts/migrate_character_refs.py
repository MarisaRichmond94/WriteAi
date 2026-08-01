"""Migrate name-based character references to `wc-` ids (LOOM-45).

Characters have had stable ids for a while, but names were what actually got
referenced: `events[].characters` and `relationships[].target` both stored a
display name. Renaming a character silently orphaned every one of them —
nothing errored, the links just stopped resolving. That is the same class of
bug the chapter-tag epic exists to kill, and it is what kept the name field in
Loom's character modal read-only.

Deliberately NOT a startup migration. It runs once, under supervision, with the
app stopped — `writer_store` rewrites each file whole under an in-process lock,
so a second writer would defeat it.

Dry-run by default. `--apply` writes, and only after taking its own timestamped
backup beside each file.

Two properties this script is built around:

  * **Idempotent.** A value that is already an id is left alone, so a re-run
    reports nothing to do. This is what makes it safe to run again if it is
    interrupted, and it is asserted directly in verify().

  * **Loud on failure.** A name that does not resolve aborts the whole
    migration before anything is written. The tempting alternative — drop the
    unresolvable reference and carry on — would silently delete real data to
    make the script succeed, which is precisely the failure mode being fixed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "writer_data"
CHARACTERS = DATA / "writer_characters.json"
EVENTS = DATA / "writer_events.json"


class Unresolvable(Exception):
    """A reference matched neither an id nor a name. Aborts the migration."""


def load(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def name_index(characters: list[dict]) -> dict[str, str]:
    """name -> id, and id -> id so an already-migrated value passes through.

    Duplicate names abort: with two "Jared Gatlin"s there is no correct answer,
    and picking one would quietly reassign somebody's relationships. There are
    no duplicates today and Loom's character modal refuses to create one, but
    this file predates that guard.
    """
    by_name: dict[str, str] = {}
    for c in characters:
        name = (c.get("name") or "").strip()
        cid = c.get("id")
        if not cid:
            raise Unresolvable(f"character record without an id: {c!r}")
        if name in by_name:
            raise Unresolvable(
                f"two characters share the name {name!r} "
                f"({by_name[name]} and {cid}) — resolve this by hand first"
            )
        if name:
            by_name[name] = cid
    # Ids map to themselves; this is the whole of the idempotency guarantee.
    for c in characters:
        by_name[c["id"]] = c["id"]
    return by_name


def resolve(value: str, index: dict[str, str], where: str) -> str:
    key = (value or "").strip()
    if key in index:
        return index[key]
    raise Unresolvable(
        f"{where}: {value!r} matches no character id or name. "
        f"Migration aborted; nothing was written."
    )


def migrate(characters: list[dict], events: dict, index: dict[str, str]):
    """Returns (characters, events, stats). Pure — writes nothing."""
    stats = {"rel_converted": 0, "rel_already": 0, "cast_converted": 0, "cast_already": 0}

    for c in characters:
        for rel in c.get("relationships") or []:
            target = rel.get("target")
            if target is None:
                continue
            resolved = resolve(target, index, f"relationship of {c.get('name')!r}")
            stats["rel_already" if resolved == target else "rel_converted"] += 1
            rel["target"] = resolved

    for ev in events.get("events") or []:
        cast = ev.get("characters")
        if not cast:
            continue
        out = []
        for member in cast:
            resolved = resolve(member, index, f"event {ev.get('title')!r}")
            stats["cast_already" if resolved == member else "cast_converted"] += 1
            out.append(resolved)
        ev["characters"] = out

    return characters, events, stats


def verify(characters: list[dict], events: dict, index: dict[str, str]) -> None:
    """Every reference is now an id, and no reference was lost.

    Checked against the in-memory result before it is written, so a bug here
    costs a failed run rather than a damaged file.
    """
    ids = {c["id"] for c in characters}
    for c in characters:
        for rel in c.get("relationships") or []:
            if rel.get("target") is not None and rel["target"] not in ids:
                raise Unresolvable(f"post-migration relationship target not an id: {rel!r}")
    for ev in events.get("events") or []:
        for member in ev.get("characters") or []:
            if member not in ids:
                raise Unresolvable(f"post-migration cast member not an id: {member!r}")
    # Idempotency, asserted rather than assumed: a second pass must be a no-op.
    _, _, again = migrate(json.loads(json.dumps(characters)), json.loads(json.dumps(events)), index)
    if again["rel_converted"] or again["cast_converted"]:
        raise Unresolvable(f"not idempotent — a second pass still converted rows: {again}")


def backup(path: Path, stamp: str) -> Path:
    dest = path.with_name(f"{path.name}.pre-loom45-{stamp}")
    shutil.copy2(path, dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the files (default: dry run)")
    args = ap.parse_args()

    characters = load(CHARACTERS)
    events = load(EVENTS)

    before = {
        "characters": len(characters),
        "rel_rows": sum(len(c.get("relationships") or []) for c in characters),
        "events": len(events.get("events") or []),
        "cast_rows": sum(len(e.get("characters") or []) for e in events.get("events") or []),
    }

    try:
        index = name_index(characters)
        characters, events, stats = migrate(characters, events, index)
        verify(characters, events, index)
    except Unresolvable as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1

    after = {
        "characters": len(characters),
        "rel_rows": sum(len(c.get("relationships") or []) for c in characters),
        "events": len(events.get("events") or []),
        "cast_rows": sum(len(e.get("characters") or []) for e in events.get("events") or []),
    }
    if before != after:
        print(f"ABORTED: row counts changed {before} -> {after}", file=sys.stderr)
        return 1

    print(f"characters: {before['characters']}  events: {before['events']}")
    print(f"relationships: {stats['rel_converted']} converted, {stats['rel_already']} already ids")
    print(f"event cast:    {stats['cast_converted']} converted, {stats['cast_already']} already ids")
    print(f"row counts unchanged: {before}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in (CHARACTERS, EVENTS):
        print(f"backed up -> {backup(path, stamp).name}")
    CHARACTERS.write_text(json.dumps(characters, ensure_ascii=False, indent=2), encoding="utf-8")
    EVENTS.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

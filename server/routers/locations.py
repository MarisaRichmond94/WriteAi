"""Locations page: the normalized gazetteer with counts + writer curation.

Raw extracted location strings live untouched in `locations`; the enrichment
gazetteer maps each raw -> (place, parent) or null. Writer curation
(renames, hides) lives in writer_data/locations.json and outranks the map.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter
from pydantic import BaseModel

from .. import writer_store
from ..deps import get_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _curation() -> dict:
    d = writer_store.load("locations.json", {})
    d.setdefault("renames", {})
    d.setdefault("hidden", [])
    return d


def _fixer():
    cur = _curation()
    renames, hidden = cur["renames"], set(cur["hidden"])

    def fix(name: str | None) -> str | None:
        if name is None:
            return None
        name = renames.get(name, name)
        return None if name in hidden else name

    return fix


def resolved_map(db) -> dict[str, tuple[str | None, str | None]]:
    """raw -> (place, parent) with writer renames/hides applied."""
    fix = _fixer()
    out: dict[str, tuple[str | None, str | None]] = {}
    try:
        rows = db.execute("SELECT raw, place, parent FROM location_map").fetchall()
    except sqlite3.OperationalError:
        return {}
    for raw, place, parent in rows:
        p = fix(place)
        out[raw] = (p, fix(parent) if p else None)
    return out


def resolved_map_v2(db) -> dict[tuple[int, str], tuple[str | None, str | None]]:
    """(book, raw) -> (place, parent) with writer renames/hides applied."""
    fix = _fixer()
    out: dict[tuple[int, str], tuple[str | None, str | None]] = {}
    try:
        rows = db.execute("SELECT book_number, raw, place, parent "
                          "FROM location_map_v2").fetchall()
    except sqlite3.OperationalError:
        return {}
    for book, raw, place, parent in rows:
        p = fix(place)
        out[(book, raw)] = (p, fix(parent) if p else None)
    return out


@router.get("/locations")
def list_locations(include_hidden: bool = False):
    s = get_state()
    cur = _curation()
    renames, hidden = cur["renames"], set(cur["hidden"])

    def fix(name):
        return renames.get(name, name) if name else None

    # v2 rows are book-scoped, so the same raw string may resolve to a
    # different place per book (a character who moves). v1 rows get a None
    # book and behave exactly as before.
    v2 = getattr(s.cfg, "enable_location_v2", False)
    try:
        if v2:
            rows = s.db.execute("SELECT book_number, raw, place, parent "
                                "FROM location_map_v2").fetchall()
        else:
            rows = [(None, raw, place, parent) for raw, place, parent in
                    s.db.execute("SELECT raw, place, parent FROM location_map")]
    except sqlite3.OperationalError:
        return {"places": [], "unmapped": 0}

    places: dict[str, dict] = {}
    unmapped = 0
    raw_to_place: dict = {}  # v1: raw -> place; v2: (book, raw) -> place
    for book, raw, place, parent in rows:
        place, parent = fix(place), fix(parent)
        if not place:
            unmapped += 1
            continue
        entry = places.setdefault(place, {
            "name": place, "parent": parent, "raw_variants": [],
            "chapter_count": 0, "event_count": 0,
            "hidden": place in hidden,
        })
        if parent and not entry["parent"]:
            entry["parent"] = parent
        if raw not in entry["raw_variants"]:
            entry["raw_variants"].append(raw)
        raw_to_place[(book, raw) if v2 else raw] = place

    # chapter presence: distinct (book, chapter) whose chunks name any variant
    chapters_by_place: dict[str, set] = {}
    for raw, book, ch in s.db.execute(
            """SELECT l.name, c.book_number, c.chapter_number
               FROM locations l JOIN chunks c ON c.chunk_id = l.chunk_id"""):
        place = raw_to_place.get((book, raw) if v2 else raw)
        if place:
            chapters_by_place.setdefault(place, set()).add((book, ch))
    for place, chs in chapters_by_place.items():
        if place in places:
            places[place]["chapter_count"] = len(chs)

    try:
        for book, loc, n in s.db.execute(
                "SELECT book_number, location, COUNT(*) FROM events "
                "WHERE location IS NOT NULL GROUP BY book_number, location"):
            place = raw_to_place.get((book, loc) if v2 else loc, fix(loc))
            if place and place in places:
                places[place]["event_count"] += n
    except sqlite3.OperationalError:
        pass

    visible = [p for p in places.values() if include_hidden or not p["hidden"]]
    visible.sort(key=lambda p: (-p["chapter_count"], p["name"]))
    return {"places": visible, "unmapped": unmapped}


class RenameBody(BaseModel):
    from_name: str
    to_name: str


@router.patch("/locations/rename")
def rename_location(body: RenameBody):
    cur = _curation()
    if body.from_name and body.to_name and body.from_name != body.to_name:
        cur["renames"][body.from_name] = body.to_name
    writer_store.save("locations.json", cur)
    return {"ok": True}


class HideBody(BaseModel):
    name: str


@router.post("/locations/hide")
def hide_location(body: HideBody):
    cur = _curation()
    if body.name not in cur["hidden"]:
        cur["hidden"].append(body.name)
    writer_store.save("locations.json", cur)
    return {"ok": True}


@router.delete("/locations/hide/{name}")
def unhide_location(name: str):
    cur = _curation()
    cur["hidden"] = [n for n in cur["hidden"] if n != name]
    writer_store.save("locations.json", cur)
    return {"ok": True}

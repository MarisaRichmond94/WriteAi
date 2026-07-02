"""Characters pane: canonical entities, detail views, and user corrections
(merge / rename / hide) persisted to writer_data/character_map.json."""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import writer_store
from ..deps import get_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _profiles(s) -> dict:
    if s.db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='character_profiles'").fetchone() is None:
        return {}
    out = {}
    for name, traits, rels, arcs in s.db.execute(
            "SELECT name, traits_json, relationships_json, arcs_json "
            "FROM character_profiles"):
        out[name] = {"traits": json.loads(traits or "[]"),
                     "relationships": {r["name"]: r["nature"]
                                       for r in json.loads(rels or "[]")},
                     "arcs": json.loads(arcs or "{}")}
    return out


@router.get("/characters")
def list_characters(min_chunks: int = 2):
    s = get_state()
    profiles = _profiles(s)
    out = []
    for e in s.canon.visible_entities():
        if len(e.chunk_ids) < min_chunks:
            continue
        summary = e.to_summary(s.canon.chunk_meta)
        prof = profiles.get(e.name, {})
        summary["traits"] = prof.get("traits", [])
        rel_natures = prof.get("relationships", {})
        summary["relationships"] = [
            {"name": n, "shared_scenes": c, "nature": rel_natures.get(n)}
            for n, c in s.canon.co_occurrence(e.name)[:10]]
        out.append(summary)
    return {"characters": out,
            "quarantined": s.canon.quarantined,
            "hidden": writer_store.character_map().get("hidden", [])}


@router.get("/characters/{name}")
def character_detail(name: str):
    s = get_state()
    s.canon.ensure_built()
    e = s.canon.entities.get(name)
    if e is None:
        raise HTTPException(404, "unknown character")
    detail = e.to_summary(s.canon.chunk_meta)
    prof = _profiles(s).get(name, {})
    detail["traits"] = prof.get("traits", [])
    detail["arcs"] = prof.get("arcs", {})
    rel_natures = prof.get("relationships", {})
    detail["relationships"] = [
        {"name": n, "shared_scenes": c, "nature": rel_natures.get(n)}
        for n, c in s.canon.co_occurrence(name)]

    names = [e.name, *e.aliases]
    knowledge = s.db.execute(
        f"""SELECT c.book_number, c.chapter_number, k.learns
            FROM character_knowledge k JOIN chunks c ON c.chunk_id = k.chunk_id
            WHERE {' OR '.join('k.character LIKE ?' for _ in names)}
            ORDER BY c.book_number, c.chapter_number""",
        [f"%{n}%" for n in names]).fetchall()
    by_book: dict = defaultdict(list)
    for b, ch, fact in knowledge:
        by_book[str(b)].append({"chapter": ch, "learns": fact})
    detail["knowledge_by_book"] = by_book

    appearances: dict = defaultdict(set)
    for cid in e.chunk_ids:
        meta = s.canon.chunk_meta.get(cid)
        if meta:
            appearances[str(meta[0])].add(meta[1])
    detail["appearances_by_book"] = {b: sorted(chs)
                                     for b, chs in appearances.items()}
    return detail


class MergeRequest(BaseModel):
    source: str   # entity or raw variant to fold in
    target: str   # canonical name it belongs to


@router.post("/characters/merge")
def merge(req: MergeRequest):
    s = get_state()
    cmap = writer_store.character_map()
    s.canon.ensure_built()
    # map the source entity AND all its aliases so the decision is complete
    entity = s.canon.entities.get(req.source)
    variants = {req.source, *(entity.aliases if entity else [])}
    for v in variants:
        cmap["map"][v] = req.target
    writer_store.save_character_map(cmap)
    s.canon._map_state = ""  # force rebuild on next read
    return {"ok": True, "mapped": sorted(variants), "target": req.target}


class RenameRequest(BaseModel):
    old: str
    new: str


@router.post("/characters/rename")
def rename(req: RenameRequest):
    s = get_state()
    s.canon.ensure_built()
    entity = s.canon.entities.get(req.old)
    if entity is None:
        raise HTTPException(404, "unknown character")
    cmap = writer_store.character_map()
    for v in {req.old, *entity.aliases}:
        cmap["map"][v] = req.new
    writer_store.save_character_map(cmap)
    s.canon._map_state = ""
    return {"ok": True}


class HideRequest(BaseModel):
    name: str


@router.post("/characters/hide")
def hide(req: HideRequest):
    cmap = writer_store.character_map()
    if req.name not in cmap["hidden"]:
        cmap["hidden"].append(req.name)
    writer_store.save_character_map(cmap)
    get_state().canon._map_state = ""
    return {"ok": True}


@router.delete("/characters/hide/{name}")
def unhide(name: str):
    cmap = writer_store.character_map()
    cmap["hidden"] = [n for n in cmap["hidden"] if n != name]
    writer_store.save_character_map(cmap)
    get_state().canon._map_state = ""
    return {"ok": True}

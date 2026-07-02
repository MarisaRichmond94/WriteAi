"""Characters API in the ported UI's contract: CharacterSummary[] with
alias provenance, relationship statuses, per-book detail, and a corrections
surface persisted to writer_data/character_map.json.

All heavy lifting stays in the canonicalizer + enrichment tables; this router
only reshapes. User corrections are name-keyed and survive re-indexing.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from .. import writer_store
from ..deps import get_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _cmap() -> dict:
    m = writer_store.character_map()
    m.setdefault("map", {})
    m.setdefault("hidden", [])
    m.setdefault("relationship_overrides", {})
    m.setdefault("gender", {})
    m.setdefault("photos", {})
    return m


def _titles(s) -> dict[int, str]:
    return dict(s.db.execute("SELECT DISTINCT book_number, book_title FROM chunks"))


def _profiles(s) -> dict:
    if s.db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='character_profiles'").fetchone() is None:
        return {}
    out = {}
    for name, traits, rels, arcs in s.db.execute(
            "SELECT name, traits_json, relationships_json, arcs_json "
            "FROM character_profiles"):
        out[name] = {"traits": json.loads(traits or "[]"),
                     "natures": {r["name"]: r.get("nature")
                                 for r in json.loads(rels or "[]")},
                     "arcs": json.loads(arcs or "{}")}
    return out


def _alias_provenance(s, canon, entity) -> list[dict]:
    """First appearance of each alias, so alias pills can cite a chapter."""
    out = []
    for alias in entity.aliases:
        row = s.db.execute(
            """SELECT book_title, chapter_number FROM chunks
               WHERE text LIKE ? ORDER BY book_number, chapter_number LIMIT 1""",
            (f"%{alias}%",)).fetchone()
        out.append({"alias": alias,
                    "book": row[0] if row else None,
                    "chapter": row[1] if row else None,
                    "context": None})
    return out


def _relationships(s, canon, name: str, cmap: dict) -> list[dict]:
    prof = _profiles(s).get(name, {})
    overrides = cmap["relationship_overrides"].get(name, {})
    rels = []
    for other, count in canon.co_occurrence(name)[:12]:
        override = overrides.get(other)
        nature = (override or {}).get("status") or prof.get("natures", {}).get(other)
        rels.append({
            "target": other,
            "character_id": other,
            "status": nature or f"{count} shared scenes",
            "gendered_status": None,
            "inferred": nature is None and override is None,
            "appearance_count": count,
            "photo_url": _photo_url(cmap, other),
        })
    return rels


def _photo_url(cmap: dict, name: str) -> str | None:
    return cmap["photos"].get(name)


def _entity_summary(s, canon, entity, cmap: dict) -> dict:
    titles = _titles(s)
    books = sorted({canon.chunk_meta[cid][0] for cid in entity.chunk_ids
                    if cid in canon.chunk_meta})
    return {
        "id": entity.name,
        "name": entity.name,
        "aliases": _alias_provenance(s, canon, entity),
        "traits": _profiles(s).get(entity.name, {}).get("traits", []),
        "relationships": _relationships(s, canon, entity.name, cmap),
        "books": [titles.get(b, f"Book {b}") for b in books],
        "is_pov": entity.is_pov,
        "pov_chapter_count": len({canon.chunk_meta[cid]
                                  for cid in entity.chunk_ids
                                  if cid in canon.chunk_meta}) if entity.is_pov else 0,
        "photo_url": _photo_url(cmap, entity.name),
        "hidden": entity.name in cmap["hidden"],
        "gender": cmap["gender"].get(entity.name),
    }


def _resolve_book(s, book: str | None) -> int | None:
    if not book:
        return None
    if book.isdigit():
        return int(book)
    for num, title in _titles(s).items():
        if title.lower() == book.lower():
            return num
    return None


@router.get("/characters")
def list_characters(book: str | None = None, raw: bool = False,
                    include_hidden: bool = False, min_chunks: int = 3):
    s = get_state()
    cmap = _cmap()
    canon = s.canon
    canon.ensure_built()
    book_num = _resolve_book(s, book)
    out = []
    for e in canon.entities.values():
        if len(e.chunk_ids) < min_chunks:
            continue
        hidden = e.name in cmap["hidden"]
        if hidden and not include_hidden:
            continue
        if book_num is not None:
            in_book = any(canon.chunk_meta.get(cid, (None,))[0] == book_num
                          for cid in e.chunk_ids)
            if not in_book:
                continue
        out.append(_entity_summary(s, canon, e, cmap))
    out.sort(key=lambda c: -next(
        (len(x.chunk_ids) for x in canon.entities.values() if x.name == c["name"]), 0))
    return out


@router.get("/characters/quarantined")
def quarantined():
    s = get_state()
    s.canon.ensure_built()
    return s.canon.quarantined


@router.get("/characters/corrections")
def corrections():
    cmap = _cmap()
    return {
        "name_overrides": {},
        "alias_removals": {},
        "alias_additions": {},
        "relationship_overrides": cmap["relationship_overrides"],
        "relationship_removals": {},
        "relationship_additions": {},
        "merges": [{"from": k, "into": v} for k, v in cmap["map"].items()],
        "hidden_characters": cmap["hidden"],
        "gender_overrides": cmap["gender"],
    }


@router.get("/characters/{name}")
def character_detail(name: str, book: str | None = None):
    s = get_state()
    cmap = _cmap()
    canon = s.canon
    canon.ensure_built()
    e = canon.entities.get(name)
    if e is None:
        raise HTTPException(404, "unknown character")
    detail = _entity_summary(s, canon, e, cmap)
    arcs = _profiles(s).get(name, {}).get("arcs", {})
    titles = _titles(s)
    detail["arc"] = {
        titles.get(int(b), f"Book {b}"): [{"chapter": 0, "insight": text,
                                           "source_quote": None}]
        for b, text in arcs.items()
    }
    return detail


@router.get("/characters/{name}/book/{book}")
def character_book_detail(name: str, book: str):
    s = get_state()
    cmap = _cmap()
    canon = s.canon
    canon.ensure_built()
    e = canon.entities.get(name)
    book_num = _resolve_book(s, book)
    if e is None or book_num is None:
        raise HTTPException(404, "unknown character or book")
    names = [e.name, *e.aliases]
    knowledge = s.db.execute(
        f"""SELECT c.chapter_number, k.learns FROM character_knowledge k
            JOIN chunks c ON c.chunk_id = k.chunk_id
            WHERE c.book_number = ? AND ({' OR '.join('k.character LIKE ?' for _ in names)})
            ORDER BY c.chapter_number""",
        [book_num, *[f"%{n}%" for n in names]]).fetchall()
    appearances = sorted({canon.chunk_meta[cid][1] for cid in e.chunk_ids
                          if canon.chunk_meta.get(cid, (None,))[0] == book_num})
    return {
        "id": name, "name": name,
        "traits": _profiles(s).get(name, {}).get("traits", []),
        "relationships": _relationships(s, canon, name, cmap),
        "knowledge": [{"text": fact, "first_revealed_chapter": ch,
                       "source_quote": None} for ch, fact in knowledge[:80]],
        "does_not_know": [],
        "active_conflicts": [],
        "chapter_appearances": appearances,
        "photo_url": _photo_url(cmap, name),
    }


# ── corrections (writes) ────────────────────────────────────────────────────

def _save(cmap: dict) -> None:
    writer_store.save_character_map(cmap)
    get_state().canon._map_state = ""  # rebuild derived view on next read


class NamePatch(BaseModel):
    old_name: str
    new_name: str
    character_id: str | None = None


@router.patch("/characters/corrections/name")
def patch_name(body: NamePatch):
    s = get_state()
    s.canon.ensure_built()
    entity = s.canon.entities.get(body.old_name)
    cmap = _cmap()
    for v in {body.old_name, *(entity.aliases if entity else [])}:
        cmap["map"][v] = body.new_name
    _save(cmap)
    return {"ok": True}


@router.delete("/characters/corrections/name/{old_name}")
def delete_name_override(old_name: str):
    cmap = _cmap()
    cmap["map"] = {k: v for k, v in cmap["map"].items() if k != old_name}
    _save(cmap)
    return {"ok": True}


class AliasBody(BaseModel):
    character: str
    alias: str
    context: str | None = None


@router.post("/characters/corrections/aliases")
def add_alias(body: AliasBody):
    cmap = _cmap()
    cmap["map"][body.alias] = body.character
    _save(cmap)
    return {"ok": True}


@router.delete("/characters/corrections/aliases")
def remove_alias(body: AliasBody):
    cmap = _cmap()
    cmap["map"].pop(body.alias, None)
    _save(cmap)
    return {"ok": True}


class RelBody(BaseModel):
    character: str
    target: str
    status: str | None = None


@router.post("/characters/corrections/relationships")
@router.patch("/characters/corrections/relationships")
def set_relationship(body: RelBody):
    cmap = _cmap()
    cmap["relationship_overrides"].setdefault(body.character, {})[body.target] = {
        "status": body.status or ""}
    _save(cmap)
    return {"ok": True}


@router.delete("/characters/corrections/relationships")
def remove_relationship(body: RelBody):
    cmap = _cmap()
    cmap["relationship_overrides"].get(body.character, {}).pop(body.target, None)
    _save(cmap)
    return {"ok": True}


class MergeBody(BaseModel):
    from_character: str
    into_character: str
    as_alias: str | None = None


@router.post("/characters/corrections/merge")
def merge(body: MergeBody):
    s = get_state()
    s.canon.ensure_built()
    entity = s.canon.entities.get(body.from_character)
    cmap = _cmap()
    for v in {body.from_character, *(entity.aliases if entity else [])}:
        cmap["map"][v] = body.into_character
    _save(cmap)
    return {"ok": True}


class HideBody(BaseModel):
    character: str


@router.post("/characters/corrections/hide")
def hide(body: HideBody):
    cmap = _cmap()
    if body.character not in cmap["hidden"]:
        cmap["hidden"].append(body.character)
    _save(cmap)
    return {"ok": True}


@router.delete("/characters/corrections/hide/{character}")
def unhide(character: str):
    cmap = _cmap()
    cmap["hidden"] = [n for n in cmap["hidden"] if n != character]
    _save(cmap)
    return {"ok": True}


class GenderBody(BaseModel):
    character: str
    gender: str


@router.patch("/characters/corrections/gender")
def set_gender(body: GenderBody):
    cmap = _cmap()
    cmap["gender"][body.character] = body.gender
    _save(cmap)
    return {"ok": True}


@router.delete("/characters/corrections/gender/{character}")
def delete_gender(character: str):
    cmap = _cmap()
    cmap["gender"].pop(character, None)
    _save(cmap)
    return {"ok": True}


@router.post("/characters/cache/invalidate")
def invalidate_cache():
    get_state().canon._map_state = ""
    return {"ok": True}


@router.post("/characters/extract")
def trigger_extract():
    """'Re-Extract Character Data' -> run the enrichment pass."""
    from .. import enrich
    from ..canonical import Canonicalizer
    s = get_state()
    if enrich.runner.running:
        raise HTTPException(409, "enrichment already running")
    enrich.runner.start(s.cfg.sqlite_path, s.cfg, lambda db: Canonicalizer(db))
    return {"ok": True}


@router.post("/characters/{name}/photo")
async def upload_photo(name: str, file: UploadFile, book: str | None = None):
    suffix = Path(file.filename or "photo.png").suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        raise HTTPException(400, "unsupported image type")
    photos_dir = writer_store.WRITER_DATA_DIR / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() else "-" for ch in name.lower())
    dest = photos_dir / f"extracted-{safe}{suffix}"
    dest.write_bytes(await file.read())
    cmap = _cmap()
    cmap["photos"][name] = f"/api/plan/photos/{dest.name}"
    _save(cmap)
    return {"photo_url": cmap["photos"][name]}

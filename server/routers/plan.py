"""Plan pane: writer-authored outline + character intent (writer_data/),
kept distinct from AI-extracted data, with sync-diff and AI review streams."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.query_router import QueryPlan, Scope

from .. import writer_store
from ..deps import get_state
from ..sse import citations_payload, stream_response

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plan")


# ── extracted view (read-only, derived from the store) ──────────────────────

def _extracted_chapters(book: int) -> dict[int, dict]:
    """chapter_number -> {heading, pov, date, bullets} from ingestion data."""
    s = get_state()
    rows = s.db.execute(
        """SELECT chapter_number, chapter_kind, pov_character, date_line,
                  metadata_json
           FROM chunks WHERE book_number = ?
           ORDER BY chapter_number, chunk_index""", (book,)).fetchall()
    chapters: dict[int, dict] = {}
    bullets: dict[int, list] = defaultdict(list)
    for ch, kind, pov, date, meta_json in rows:
        chapters.setdefault(ch, {
            "chapter": ch,
            "heading": "Prologue" if kind == "prologue" else f"Chapter {ch}",
            "pov": pov, "date": date})
        if meta_json and len(bullets[ch]) < 6:
            bullets[ch].extend(json.loads(meta_json).get("key_events", []))
    for ch in chapters:
        chapters[ch]["bullets"] = bullets[ch][:6]
    return chapters


def _seed_outline(book: int) -> list[dict]:
    return [{
        "id": f"ch-{book}-{ch['chapter']}",
        "book": book,
        "chapter": ch["chapter"],
        "position": float(ch["chapter"]),
        "status": "synced",
        "heading": ch["heading"],
        "pov": ch["pov"] or "",
        "date": ch["date"],
        "writer_summary": "",
        "extracted_bullets": ch["bullets"],
        "notes": None,
    } for ch in sorted(_extracted_chapters(book).values(),
                       key=lambda c: c["chapter"])]


# ── outline CRUD ────────────────────────────────────────────────────────────

@router.get("/outline/{book}")
def get_outline(book: int):
    outlines = writer_store.plan_outline()
    key = str(book)
    if key not in outlines:
        outlines[key] = _seed_outline(book)
        writer_store.save_plan_outline(outlines)
    return {"book": book, "chapters": sorted(outlines[key],
                                             key=lambda c: c["position"])}


class OutlinePut(BaseModel):
    chapters: list[dict]


@router.put("/outline/{book}")
def put_outline(book: int, body: OutlinePut):
    outlines = writer_store.plan_outline()
    outlines[str(book)] = body.chapters
    writer_store.save_plan_outline(outlines)
    return {"ok": True}


class NewChapter(BaseModel):
    position: float
    heading: str = "New chapter"
    pov: str = ""
    writer_summary: str = ""


@router.post("/outline/{book}/chapter")
def add_chapter(book: int, body: NewChapter):
    outlines = writer_store.plan_outline()
    key = str(book)
    outlines.setdefault(key, _seed_outline(book))
    ch = {"id": f"plan-{uuid.uuid4().hex[:8]}", "book": book, "chapter": None,
          "position": body.position, "status": "planned",
          "heading": body.heading, "pov": body.pov, "date": None,
          "writer_summary": body.writer_summary, "extracted_bullets": [],
          "notes": None}
    outlines[key].append(ch)
    writer_store.save_plan_outline(outlines)
    return ch


@router.delete("/outline/{book}/chapter/{chapter_id}")
def delete_chapter(book: int, chapter_id: str):
    outlines = writer_store.plan_outline()
    key = str(book)
    before = len(outlines.get(key, []))
    outlines[key] = [c for c in outlines.get(key, []) if c["id"] != chapter_id]
    writer_store.save_plan_outline(outlines)
    return {"ok": True, "deleted": before - len(outlines[key])}


# ── resync: outline vs extracted ────────────────────────────────────────────

@router.get("/resync/{book}")
def resync_preview(book: int):
    extracted = _extracted_chapters(book)
    outline = {c["chapter"]: c for c in writer_store.plan_outline().get(str(book), [])
               if c.get("chapter") is not None}
    diffs, new_chapters = [], []
    for ch, ext in sorted(extracted.items()):
        oc = outline.get(ch)
        if oc is None:
            new_chapters.append(ch)
            continue
        for field, ext_val in (("pov", ext["pov"] or ""), ("date", ext["date"]),
                               ("extracted_bullets", ext["bullets"])):
            cur = oc.get(field if field != "extracted_bullets" else "extracted_bullets")
            if cur != ext_val:
                diffs.append({"id": f"{ch}:{field}", "chapter": ch, "field": field,
                              "outline_value": cur, "extracted_value": ext_val})
    removed = [ch for ch in outline if ch not in extracted]
    return {"book": book, "diffs": diffs, "new_chapters": new_chapters,
            "removed_chapters": removed,
            "status": "ready" if (diffs or new_chapters or removed) else "in_sync"}


class ResyncApprove(BaseModel):
    diff_ids: list[str] = []
    add_new_chapters: bool = True
    remove_missing: bool = False


@router.post("/resync/{book}/approve")
def resync_approve(book: int, body: ResyncApprove):
    extracted = _extracted_chapters(book)
    outlines = writer_store.plan_outline()
    key = str(book)
    chapters = outlines.get(key, [])
    by_num = {c["chapter"]: c for c in chapters if c.get("chapter") is not None}

    approved = set(body.diff_ids)
    for ch, ext in extracted.items():
        oc = by_num.get(ch)
        if oc is None:
            if body.add_new_chapters:
                seeded = next(c for c in _seed_outline(book) if c["chapter"] == ch)
                chapters.append(seeded)
            continue
        if f"{ch}:pov" in approved:
            oc["pov"] = ext["pov"] or ""
        if f"{ch}:date" in approved:
            oc["date"] = ext["date"]
        if f"{ch}:extracted_bullets" in approved:
            oc["extracted_bullets"] = ext["bullets"]
        oc["status"] = "synced"
    if body.remove_missing:
        chapters = [c for c in chapters
                    if c.get("chapter") is None or c["chapter"] in extracted]
    outlines[key] = chapters
    writer_store.save_plan_outline(outlines)
    return get_outline(book)


# ── writer characters (authorial intent) ────────────────────────────────────

def _seed_writer_characters() -> list[dict]:
    s = get_state()
    seeded = []
    for e in s.canon.visible_entities()[:24]:
        if e.kind == "descriptor":
            continue
        category = ("main" if e.is_pov
                    else "secondary" if len(e.chunk_ids) >= 50 else "tertiary")
        books = sorted({s.canon.chunk_meta[cid][0] for cid in e.chunk_ids
                        if cid in s.canon.chunk_meta})
        seeded.append({
            "id": f"wc-{uuid.uuid4().hex[:8]}", "name": e.name,
            "category": category, "role": None,
            "aliases": ", ".join(e.aliases) or None, "traits": [],
            "arc_notes": None, "goals": None, "relationships": [],
            "books": books,
        })
    return seeded


@router.get("/characters")
def get_writer_characters():
    chars = writer_store.writer_characters()
    if not chars:
        chars = _seed_writer_characters()
        writer_store.save_writer_characters(chars)
        return {"characters": chars, "seeded": True}
    return {"characters": chars, "seeded": False}


class CharactersPut(BaseModel):
    characters: list[dict]


@router.put("/characters")
def put_writer_characters(body: CharactersPut):
    writer_store.save_writer_characters(body.characters)
    return {"ok": True}


@router.put("/characters/{char_id}")
def put_writer_character(char_id: str, body: dict):
    chars = writer_store.writer_characters()
    for i, c in enumerate(chars):
        if c["id"] == char_id:
            body["id"] = char_id
            chars[i] = body
            writer_store.save_writer_characters(chars)
            return body
    raise HTTPException(404, "unknown character")


@router.delete("/characters/{char_id}")
def delete_writer_character(char_id: str):
    chars = writer_store.writer_characters()
    writer_store.save_writer_characters([c for c in chars if c["id"] != char_id])
    return {"ok": True}


@router.get("/characters/{char_id}/extracted")
def writer_character_extracted(char_id: str):
    """The AI-extracted profile matching a writer character (Compare panel)."""
    chars = writer_store.writer_characters()
    wc = next((c for c in chars if c["id"] == char_id), None)
    if wc is None:
        raise HTTPException(404, "unknown character")
    from .characters import character_detail
    s = get_state()
    s.canon.ensure_built()
    name = wc["name"] if wc["name"] in s.canon.entities \
        else s.canon.resolve(wc["name"])
    if not name or name not in s.canon.entities:
        return {"found": False, "name": wc["name"]}
    detail = character_detail(name)
    detail["found"] = True
    return detail


# ── AI review streams ───────────────────────────────────────────────────────

class OutlineReviewRequest(BaseModel):
    book: int
    chapter_ids: list[str] = []
    message: str = ""


@router.post("/outline/review/stream")
def outline_review_stream(req: OutlineReviewRequest):
    s = get_state()
    chapters = writer_store.plan_outline().get(str(req.book), [])
    if req.chapter_ids:
        chapters = [c for c in chapters if c["id"] in req.chapter_ids]
    if not chapters:
        raise HTTPException(400, "no outline chapters to review")

    def generate():
        outline_text = json.dumps(
            [{k: c.get(k) for k in ("chapter", "heading", "pov", "date",
                                    "writer_summary", "extracted_bullets")}
             for c in sorted(chapters, key=lambda c: c["position"])],
            ensure_ascii=False, indent=1)
        question = req.message or (
            "Review this outline for structural issues: pacing across chapters, "
            "POV balance, dropped threads, and where planned chapters conflict "
            "with what the written chapters establish.")
        plan = QueryPlan(
            question=f"OUTLINE (Book {req.book}):\n{outline_text}\n\n{question}",
            qtype="general", scope=Scope(book_min=req.book, book_max=req.book))
        excerpts, notes = s.retriever.retrieve(
            QueryPlan(question=question + " " + " ".join(
                c.get("writer_summary") or c["heading"] for c in chapters[:10]),
                qtype="general", scope=plan.scope))
        answerer = s.new_answerer()
        for delta in answerer.answer_stream(plan, excerpts, notes):
            yield {"type": "chunk", "content": delta}
        yield citations_payload(excerpts)
        yield {"type": "usage", "cost_usd": answerer.actual_cost_usd}

    return stream_response(generate())


class CharacterReviewRequest(BaseModel):
    character_id: str
    message: str = ""


@router.post("/character/review/stream")
def character_review_stream(req: CharacterReviewRequest):
    s = get_state()
    wc = next((c for c in writer_store.writer_characters()
               if c["id"] == req.character_id), None)
    if wc is None:
        raise HTTPException(404, "unknown character")

    def generate():
        intent = json.dumps({k: wc.get(k) for k in (
            "name", "category", "role", "traits", "goals", "arc_notes",
            "relationships")}, ensure_ascii=False, indent=1)
        question = req.message or (
            "Compare my stated intent for this character against how they "
            "actually come across in the written books. Where does the text "
            "support the intent, where does it diverge, and what's missing?")
        plan = QueryPlan(
            question=f"WRITER'S INTENT for {wc['name']}:\n{intent}\n\n{question}",
            qtype="general", characters=[wc["name"]])
        excerpts, notes = s.retriever.retrieve(QueryPlan(
            question=f"{wc['name']} personality goals relationships arc",
            qtype="sentiment", characters=[wc["name"]]))
        answerer = s.new_answerer()
        for delta in answerer.answer_stream(plan, excerpts, notes):
            yield {"type": "chunk", "content": delta}
        yield citations_payload(excerpts)
        yield {"type": "usage", "cost_usd": answerer.actual_cost_usd}

    return stream_response(generate())

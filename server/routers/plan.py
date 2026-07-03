"""Plan pane: writer-authored outline + character intent (writer_data/),
kept distinct from AI-extracted data, with sync-diff and AI review streams."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
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

def _bullets_html(bullets: list[str]) -> str:
    """key_events -> a TipTap-compatible bullet list for the card summary."""
    import html
    items = "".join(f"<li><p>{html.escape(b)}</p></li>" for b in bullets)
    return f"<ul>{items}</ul>" if items else ""


@router.get("/outline/{book}")
def get_outline(book: int):
    outlines = writer_store.plan_outline()
    key = str(book)
    if key not in outlines:
        outlines[key] = _seed_outline(book)
        writer_store.save_plan_outline(outlines)
    # Backfill: cards display writer_summary; where the writer hasn't written
    # one yet, show the enriched prose chapter summary (falling back to key
    # events as bullets). Only ever fills EMPTY summaries — never overwrites
    # the writer's words.
    import html as _html
    s = get_state()
    try:
        prose = dict(s.db.execute(
            "SELECT chapter_number, summary FROM chapter_summaries "
            "WHERE book_number = ?", (book,)))
    except Exception:
        prose = {}
    changed = False
    for c in outlines[key]:
        ws = (c.get("writer_summary") or "").strip()
        # untouched bullet auto-backfill upgrades itself once prose exists;
        # anything the writer edited (even one character) never matches
        if ws and ws != _bullets_html(c.get("extracted_bullets") or []):
            continue
        if c.get("chapter") in prose:
            c["writer_summary"] = f"<p>{_html.escape(prose[c['chapter']])}</p>"
            changed = True
        elif c.get("extracted_bullets"):
            c["writer_summary"] = _bullets_html(c["extracted_bullets"])
            changed = True
    if changed:
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
    return get_outline(book)


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

def _book_name(book: int) -> str:
    s = get_state()
    row = s.db.execute("SELECT book_title FROM chunks WHERE book_number = ? LIMIT 1",
                       (book,)).fetchone()
    return row[0] if row else f"Book {book}"


@router.get("/resync/{book}")
def resync_preview(book: int):
    """Diff the writer's outline against the extracted chapters, in the shape
    the resync modal expects: per-chapter field diffs (approval granularity is
    the chapter card) plus numbering assignments for newly written chapters."""
    extracted = _extracted_chapters(book)
    outline_chapters = writer_store.plan_outline().get(str(book), [])
    outline = {c["chapter"]: c for c in outline_chapters
               if c.get("chapter") is not None}
    planned = [c for c in outline_chapters if c.get("chapter") is None]

    field_diffs, numbering = [], []
    for ch, ext in sorted(extracted.items()):
        oc = outline.get(ch)
        if oc is None:
            numbering.append({
                "outline_id": f"new-{book}-{ch}",
                "outline_heading": ext["heading"],
                "old_chapter": None,
                "new_chapter": ch,
                "is_renumbered": False,
            })
            continue
        diffs = []
        for field, ext_val, old_val in (
                ("pov", ext["pov"] or "", oc.get("pov")),
                ("date", ext["date"], oc.get("date")),
                ("extracted_bullets", ext["bullets"], oc.get("extracted_bullets"))):
            if old_val != ext_val:
                # bullets travel as JSON strings (the diff row parses them)
                enc = (lambda v: json.dumps(v, ensure_ascii=False)
                       if isinstance(v, list) else v)
                diffs.append({"field": field, "old": enc(old_val), "new": enc(ext_val)})
        if diffs:
            field_diffs.append({"chapter_id": oc["id"], "chapter": ch,
                                "heading": oc.get("heading") or f"Chapter {ch}",
                                "diffs": diffs})
    return {
        "book": _book_name(book),
        "status": "partial" if planned else "ready",
        "conflict_reason": None,
        "numbering": numbering,
        "field_diffs": field_diffs,
        "unmatched_outline_count": len(planned),
    }


class ResyncApprove(BaseModel):
    book: str | None = None
    approved_diff_ids: list[str] = []   # outline chapter card ids
    diff_ids: list[str] = []            # legacy per-field ids (still accepted)


@router.post("/resync/{book}/approve")
def resync_approve(book: int, body: ResyncApprove):
    extracted = _extracted_chapters(book)
    outlines = writer_store.plan_outline()
    key = str(book)
    chapters = outlines.get(key, [])
    by_num = {c["chapter"]: c for c in chapters if c.get("chapter") is not None}
    approved_cards = set(body.approved_diff_ids)
    approved_fields = set(body.diff_ids)

    for ch, ext in extracted.items():
        oc = by_num.get(ch)
        if oc is None:  # newly written chapter — always added
            seeded = next(c for c in _seed_outline(book) if c["chapter"] == ch)
            chapters.append(seeded)
            continue
        card_approved = oc["id"] in approved_cards
        if card_approved or f"{ch}:pov" in approved_fields:
            oc["pov"] = ext["pov"] or ""
        if card_approved or f"{ch}:date" in approved_fields:
            oc["date"] = ext["date"]
        if card_approved or f"{ch}:extracted_bullets" in approved_fields:
            oc["extracted_bullets"] = ext["bullets"]
        oc["status"] = "synced"
    outlines[key] = chapters
    writer_store.save_plan_outline(outlines)
    return get_outline(book)


# ── writer characters (authorial intent) ────────────────────────────────────

def _book_titles() -> dict[int, str]:
    s = get_state()
    return dict(s.db.execute(
        "SELECT DISTINCT book_number, book_title FROM chunks"))


def _seed_writer_characters() -> list[dict]:
    s = get_state()
    titles = _book_titles()
    seeded = []
    for e in s.canon.visible_entities()[:24]:
        if e.kind != "character":
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
            # the UI matches characters to books by book NAME
            "books": [titles.get(b, f"Book {b}") for b in books],
            "photo_url": None,
        })
    return seeded


@router.get("/characters")
def get_writer_characters():
    chars = writer_store.writer_characters()
    if not chars:
        chars = _seed_writer_characters()
        writer_store.save_writer_characters(chars)
        return {"characters": chars, "seeded": True}
    # drop auto-seeded entries that classification now marks as non-characters
    # ("The man", role tags) — but never anything the writer has edited
    s = get_state()
    s.canon.ensure_built()

    def untouched_junk(c: dict) -> bool:
        e = s.canon.entities.get(c["name"])
        is_junk = e is not None and e.kind != "character"
        edited = bool(c.get("goals") or c.get("arc_notes") or c.get("traits")
                      or c.get("relationships") or c.get("role"))
        return is_junk and not edited

    pruned = [c for c in chars if not untouched_junk(c)]
    changed = len(pruned) != len(chars)
    chars = pruned

    # self-heal older records that stored book numbers instead of names
    titles = _book_titles()
    for c in chars:
        fixed = [titles.get(b, b) if isinstance(b, int) else b
                 for b in c.get("books", [])]
        if fixed != c.get("books"):
            c["books"] = fixed
            changed = True
        if "photo_url" not in c:
            c["photo_url"] = None
            changed = True
    if changed:
        writer_store.save_writer_characters(chars)
    return {"characters": chars, "seeded": False}


class CharactersPut(BaseModel):
    characters: list[dict]


@router.put("/characters")
def put_writer_characters(body: CharactersPut):
    writer_store.save_writer_characters(body.characters)
    return {"ok": True}


class CharactersImport(BaseModel):
    names: list[str]


@router.post("/characters/import")
def import_writer_characters(body: CharactersImport):
    """Selectively import AI-extracted characters (name, aliases,
    relationships with known natures, photo) as writer characters.
    Names already present are skipped, never merged or overwritten."""
    from .characters import _cmap, _photo_url, _profiles, _relationships

    s = get_state()
    s.canon.ensure_built()
    cmap = _cmap()
    titles = _book_titles()
    chars = writer_store.writer_characters()
    existing = {c.get("name") for c in chars}
    imported, skipped = [], []
    for name in body.names:
        e = s.canon.entities.get(name)
        if e is None or e.kind != "character" or name in existing:
            skipped.append(name)
            continue
        books = sorted({s.canon.chunk_meta[cid][0] for cid in e.chunk_ids
                        if cid in s.canon.chunk_meta})
        rels = _relationships(s, s.canon, name, cmap)
        entry = {
            "id": f"wc-{uuid.uuid4().hex[:8]}", "name": name,
            "category": ("main" if e.is_pov
                         else "secondary" if len(e.chunk_ids) >= 50 else "tertiary"),
            "role": None,
            "aliases": ", ".join(e.aliases) or None,
            "traits": [], "arc_notes": None, "goals": None,
            "relationships": [{"target": r["target"], "nature": r["status"]}
                              for r in rels if r["status"]],
            "books": [titles.get(b, f"Book {b}") for b in books],
            "photo_url": _photo_url(cmap, name),
        }
        chars.append(entry)
        imported.append(entry)
    if imported:
        writer_store.save_writer_characters(chars)
    return {"imported": imported, "skipped": skipped}


@router.put("/characters/{char_id}")
def put_writer_character(char_id: str, body: dict):
    """Upsert: updates in place, or appends when the id is new (the UI
    creates fresh characters this way)."""
    chars = writer_store.writer_characters()
    body["id"] = char_id
    for i, c in enumerate(chars):
        if c["id"] == char_id:
            chars[i] = body
            break
    else:
        chars.append(body)
    writer_store.save_writer_characters(chars)
    return body


@router.post("/characters/{char_id}/photo")
async def upload_character_photo(char_id: str, file: UploadFile):
    """Store a character portrait under writer_data/photos/ (writer data,
    never touched by AI or re-indexing)."""
    suffix = Path(file.filename or "photo.png").suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        raise HTTPException(400, "unsupported image type")
    photos_dir = writer_store.WRITER_DATA_DIR / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    # one photo per character: clear previous extensions
    for old in photos_dir.glob(f"{char_id}.*"):
        old.unlink()
    dest = photos_dir / f"{char_id}{suffix}"
    dest.write_bytes(await file.read())
    photo_url = f"/api/plan/photos/{dest.name}"
    chars = writer_store.writer_characters()
    for c in chars:
        if c["id"] == char_id:
            c["photo_url"] = photo_url
    writer_store.save_writer_characters(chars)
    return {"photo_url": photo_url}


@router.get("/photos/{filename}")
def get_character_photo(filename: str):
    from fastapi.responses import FileResponse
    path = (writer_store.WRITER_DATA_DIR / "photos" / Path(filename).name)
    if not path.exists():
        raise HTTPException(404, "no photo")
    return FileResponse(path)


@router.delete("/characters/{char_id}")
def delete_writer_character(char_id: str):
    chars = writer_store.writer_characters()
    writer_store.save_writer_characters([c for c in chars if c["id"] != char_id])
    return {"ok": True}


@router.get("/characters/{char_id}/extracted")
def writer_character_extracted(char_id: str):
    """The AI-extracted profile matching a writer character, in the shape the
    Compare panel renders: aliases, traits, relationships with status/inferred,
    knowledge summary, active conflicts."""
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
        return {}
    detail = character_detail(name)
    knowledge_count = sum(len(v) for v in detail["knowledge_by_book"].values())
    return {
        "aliases": detail["aliases"],
        "role": "POV character" if detail["is_pov"] else None,
        "traits": detail["traits"],
        "relationships": [
            {"target": r["name"],
             "status": r["nature"] or f"{r['shared_scenes']} shared scenes",
             "gendered_status": None,
             "inferred": r["nature"] is None}
            for r in detail["relationships"][:10]
        ],
        "knowledge_gained": (
            f"{knowledge_count} facts learned across "
            f"{len(detail['knowledge_by_book'])} book(s)"),
        "active_conflicts": [],
    }


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

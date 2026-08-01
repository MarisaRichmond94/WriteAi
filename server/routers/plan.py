"""Plan pane: writer-authored outline + character intent (writer_data/),
kept distinct from AI-extracted data, with sync-diff and AI review streams."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from src.discovery import loom_book_id_for
from src.query_router import QueryPlan, Scope

from .. import outline_store, writer_store
from ..deps import get_state
from ..sse import citations_payload, stream_response

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plan")


# ── extracted view (read-only, derived from the store) ──────────────────────

def _extracted_chapters(book: int) -> dict[int, dict]:
    """chapter_number -> {heading, pov, date, bullets} from ingestion data."""
    s = get_state()
    # Prefer the stable Loom id (KAN-12). book_number is positional, so after
    # an insertion or reorder this query would pull another book's chapters and
    # _auto_reconcile would fold them into this book's outline cards. Falls back
    # to book_number when identity is unknown or nothing indexed carries it yet.
    _SELECT = """SELECT chapter_number, chapter_kind, pov_character, date_line,
                        metadata_json
                 FROM chunks WHERE {} = ?
                 ORDER BY chapter_number, chunk_index"""
    rows = []
    loom_book_id = loom_book_id_for(s.cfg, book)
    if loom_book_id:
        rows = s.db.execute(_SELECT.format("loom_book_id"),
                            (loom_book_id,)).fetchall()
    if not rows:
        rows = s.db.execute(_SELECT.format("book_number"), (book,)).fetchall()
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


def _sync_state(in_sync: bool, num_to_loom: dict[int, str]) -> str:
    """Classify a book's index-vs-manifest state for the outline response.

    "unknown" means no readable Loom manifest, so `_auto_reconcile` is inert —
    the outline's chapter numbering will NOT self-correct after edits. Callers
    surface this so the silent no-op is visible instead of looking like drift.
    """
    if not num_to_loom:
        return "unknown"
    return "synced" if in_sync else "behind"


def _is_machine_written(card: dict) -> bool:
    """True when nothing on this card came from the writer.

    Same provenance test the reconcile loop already trusts to decide whether a
    summary may be cleared: machine content matches `summary_source` exactly (or
    is the auto-backfill of its own bullets), and a writer edit of even one
    character breaks the match. Notes are writer-only, so any note makes a card
    writer-authored regardless of its summary.
    """
    if (card.get("notes") or "").strip():
        return False
    ws = (card.get("writer_summary") or "").strip()
    if not ws:
        return True
    return (ws == (card.get("summary_source") or "").strip()
            or ws == _bullets_html(card.get("extracted_bullets") or []))


def _auto_reconcile(book: int, cards: list[dict],
                    in_sync: bool, num_to_loom: dict[int, str]) -> bool:
    """Fold newly written / renumbered chapters into the outline without ever
    touching writer-authored content. Runs only when the index matches Loom's
    manifest ("no drift") — under drift the numbering is about to change
    again, so reconciling would churn cards twice; the manual Sync flow
    remains for conflicts. Cards are matched by the manifest's stable Loom
    chapter id once stamped (so a mid-book insertion renumbers cards instead
    of cross-wiring their content); plain number match is the first-time
    fallback. Returns True when cards changed."""
    if not in_sync or not num_to_loom:
        return False
    extracted = _extracted_chapters(book)
    # Subset, not equality: canon may legitimately contain chapters the index
    # cannot hold. A stubbed chapter (wordCount 0, written later) produces no
    # chunks, so demanding equality blocked reconcile for its whole book
    # forever. `in_sync` above is the authoritative freshness signal and is
    # already stub-aware (see book_sync_state); this guard only needs to catch
    # the genuine inconsistency — the index holding chapters canon does not.
    if not set(extracted) <= set(num_to_loom):  # ingest raced the check — skip
        return False

    by_loom = {c["loom_id"]: c for c in cards if c.get("loom_id")}
    by_num = {c["chapter"]: c for c in cards
              if c.get("chapter") is not None and not c.get("loom_id")}
    changed = False
    # Cards left stranded when a stamped card is renumbered ONTO the number an
    # unstamped card already occupies. by_loom wins the match, so the unstamped
    # card is never claimed by any iteration and lingers as a visible duplicate.
    # This is how book 3 ended up with two chapter-68 cards holding identical
    # summaries: ch-3-65-… was created at 65, renumbered to 68, and landed on
    # the seeded ch-3-68.
    superseded: list[dict] = []
    # Cards this pass matched or created. Anything left unclaimed at the end is
    # a candidate for pruning -- computed AFTER the loop, never before: a card
    # about to be renumbered (65 -> 68) still holds its OLD number here, so
    # judging it against canon up front would delete exactly the cards the loop
    # is on its way to fix.
    claimed: set[int] = set()

    for num in sorted(extracted):
        loom_id = num_to_loom[num]
        ext = extracted[num]
        card = by_loom.get(loom_id) or by_num.get(num)
        twin = by_num.get(num)
        if twin is not None and twin is not card:
            superseded.append(twin)
        if card is None:  # newly written chapter — a card can only be added
            cards.append({
                "id": f"ch-{book}-{num}-{uuid.uuid4().hex[:6]}",
                "book": book, "chapter": num, "position": float(num),
                "status": "synced", "heading": ext["heading"],
                "pov": ext["pov"] or "", "date": ext["date"],
                "writer_summary": "", "extracted_bullets": ext["bullets"],
                "notes": None, "loom_id": loom_id,
            })
            claimed.add(id(cards[-1]))
            changed = True
            continue
        claimed.add(id(card))
        touched = False
        if card.get("loom_id") != loom_id:
            card["loom_id"] = loom_id
            touched = True
        old_num = card.get("chapter")
        if old_num != num:
            card["chapter"] = num
            card["position"] = float(num)
            if card.get("heading") == f"Chapter {old_num}":
                card["heading"] = f"Chapter {num}"
            touched = True
        if card.get("extracted_bullets") != ext["bullets"]:
            # A summary the machine wrote (provenance match, or the exact
            # auto-backfill of the old bullets) is cleared so the backfill in
            # get_outline refills it from this chapter's current prose
            # summary. Writer words never match and are kept.
            ws = (card.get("writer_summary") or "").strip()
            if ws and (ws == (card.get("summary_source") or "").strip()
                       or ws == _bullets_html(card.get("extracted_bullets") or [])):
                card["writer_summary"] = ""
                card["summary_source"] = None
            card["extracted_bullets"] = ext["bullets"]
            touched = True
        # pov/date mirror the manuscript for a written chapter — the walk is
        # authoritative for both. Authorial intent lives on planned cards
        # (chapter=None), which this loop never visits.
        if (card.get("pov") or "") != (ext["pov"] or ""):
            card["pov"] = ext["pov"] or ""
            touched = True
        if card.get("date") != ext["date"]:
            card["date"] = ext["date"]
            touched = True
        if touched:
            card["status"] = "synced"
            changed = True

    # Cards the loop never claimed and whose number is not in canon. The loop
    # only visits numbers present in `extracted`, so these are never inspected
    # and survive forever -- reconcile adds and updates but has never pruned.
    # Faded carried a phantom `ch-2-93` this way: canon ran 0..92, the outline
    # had 94 cards, and the extra one rendered with a bullets fallback because
    # no chapter summary existed for it.
    #
    # Safe because of the guard above: `extracted` is asserted equal to the
    # manifest's chapter set before we get here, so "not in canon" means the
    # chapter is genuinely gone -- not that the ingest is lagging. Planned cards
    # (chapter=None) are skipped: authorial intent, never derived.
    canon_numbers = set(extracted)
    canon_ids = set(num_to_loom.values())

    def _left_canon(c: dict) -> bool:
        """An unclaimed card that no longer corresponds to a canon chapter.

        Two distinct cases, and keying only on the NUMBER misses the second:

        * unstamped -> judge by number. A card sitting at a number canon no
          longer contains is a leftover (Faded's phantom `ch-2-93`).
        * stamped -> judge by IDENTITY. Its number may still exist while being
          occupied by a different chapter entirely. Faded hit exactly this:
          un-canonising Bonus Chapter 3 left `ch-2-47` holding a loom_id absent
          from the manifest, while another chapter renumbered INTO 47. Judging
          by number kept the orphan and reconcile added a second card beside
          it -- a duplicate created by the very pass meant to prevent them.
        """
        if c.get("chapter") is None:
            return False                      # planned card, never derived
        if c.get("loom_id"):
            return c["loom_id"] not in canon_ids
        return c["chapter"] not in canon_numbers

    superseded.extend(c for c in cards
                      if id(c) not in claimed and _left_canon(c))

    # Drop stranded cards -- duplicates and out-of-canon leftovers alike -- but
    # ONLY the ones the machine wrote. A card carrying writer words or notes is
    # kept and reported: silently deleting writing to tidy the outline would be
    # far worse than leaving a stale card visible, and the manual Sync flow
    # exists for exactly that conflict.
    for twin in superseded:
        if twin not in cards:      # defensive: same card stranded twice
            continue
        if not _is_machine_written(twin):
            log.warning(
                "outline book %d: chapter %s has a duplicate card (%s) carrying "
                "writer content — leaving both in place for manual resolution",
                book, twin.get("chapter"), twin.get("id"))
            continue
        cards.remove(twin)
        changed = True
        log.info("outline book %d: removed superseded duplicate card %s at "
                 "chapter %s (machine-written, no writer content)",
                 book, twin.get("id"), twin.get("chapter"))
    return changed


@router.get("/outline/{book}")
def get_outline(book: int):
    from .sync import book_sync_state

    outlines = outline_store.load_outlines()
    key = outline_store.outline_key(book)
    if key not in outlines:
        outlines[key] = _seed_outline(book)
        outline_store.save_outlines(outlines)
    in_sync, num_to_loom = book_sync_state(get_state(), book)
    sync_state = _sync_state(in_sync, num_to_loom)
    if sync_state == "unknown":
        log.warning(
            "outline book %d: no readable Loom manifest — auto-reconcile is "
            "inert, so chapter numbering will not self-correct after edits", book)
    if _auto_reconcile(book, outlines[key], in_sync, num_to_loom):
        outline_store.save_outlines(outlines)
    # Backfill: cards display writer_summary; where the writer hasn't written
    # one, show the enriched prose chapter summary (falling back to key
    # events as bullets). `summary_source` records exactly what the machine
    # wrote, so machine content keeps refreshing itself when enrichment (or
    # chapter numbering) changes, while anything the writer edited — even by
    # one character — stops matching and is never overwritten again.
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
        machine = (not ws
                   or ws == (c.get("summary_source") or "").strip()
                   or ws == _bullets_html(c.get("extracted_bullets") or []))
        if not machine:
            continue
        if c.get("chapter") in prose:
            new = f"<p>{_html.escape(prose[c['chapter']])}</p>"
        elif c.get("extracted_bullets"):
            new = _bullets_html(c["extracted_bullets"])
        else:
            continue
        if ws != new:
            c["writer_summary"] = new
            c["summary_source"] = new
            changed = True
        elif c.get("summary_source") != new:
            c["summary_source"] = new  # adopt provenance for legacy backfills
            changed = True
    if changed:
        outline_store.save_outlines(outlines)
    return {"book": book, "sync_state": sync_state,
            "chapters": sorted(outlines[key], key=lambda c: c["position"])}


class OutlinePut(BaseModel):
    chapters: list[dict]


@router.put("/outline/{book}")
def put_outline(book: int, body: OutlinePut):
    outlines = outline_store.load_outlines()
    outlines[outline_store.outline_key(book)] = body.chapters
    outline_store.save_outlines(outlines)
    return get_outline(book)


class NewChapter(BaseModel):
    position: float
    heading: str = "New chapter"
    pov: str = ""
    writer_summary: str = ""


@router.post("/outline/{book}/chapter")
def add_chapter(book: int, body: NewChapter):
    outlines = outline_store.load_outlines()
    key = outline_store.outline_key(book)
    outlines.setdefault(key, _seed_outline(book))
    ch = {"id": f"plan-{uuid.uuid4().hex[:8]}", "book": book, "chapter": None,
          "position": body.position, "status": "planned",
          "heading": body.heading, "pov": body.pov, "date": None,
          "writer_summary": body.writer_summary, "extracted_bullets": [],
          "notes": None}
    outlines[key].append(ch)
    outline_store.save_outlines(outlines)
    return ch


@router.delete("/outline/{book}/chapter/{chapter_id}")
def delete_chapter(book: int, chapter_id: str):
    outlines = outline_store.load_outlines()
    key = outline_store.outline_key(book)
    before = len(outlines.get(key, []))
    outlines[key] = [c for c in outlines.get(key, []) if c["id"] != chapter_id]
    outline_store.save_outlines(outlines)
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
    outline_chapters = outline_store.chapters_for(book)
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
    outlines = outline_store.load_outlines()
    key = outline_store.outline_key(book)
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
    outline_store.save_outlines(outlines)
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


def _safe_photo_stem(char_id: str) -> str:
    """Reject any id that is not a plain filename component.

    This id is interpolated into a GLOB and the matches are then unlinked, so
    a metacharacter does not merely fail — it widens. `*` turns the pattern
    into `*.*`, which matches every portrait in the directory and deletes all
    of them. Verified, not theoretical.

    Deliberately checks filename SAFETY, not id FORMAT: ids are mostly
    `wc-<hex>` but at least one real character predates that (`draft-<ms>`),
    so pinning the `wc-` shape would break a live record while adding nothing
    — `*` is no more allowed in one shape than the other.

    settings.py's `_safe_slug` guards the book-cover routes the same way; this
    is the one glob that was missed.
    """
    if not char_id or not re.fullmatch(r"[A-Za-z0-9_-]+", char_id):
        raise HTTPException(400, "invalid character id")
    return char_id


@router.post("/characters/{char_id}/photo")
async def upload_character_photo(char_id: str, file: UploadFile):
    """Store a character portrait under writer_data/photos/ (writer data,
    never touched by AI or re-indexing)."""
    char_id = _safe_photo_stem(char_id)
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
    # A character's photo is stored under a stable filename (e.g.
    # extracted-jared-gatlin.jpg) and overwritten in place when the writer
    # uploads a new one. Without this header the browser heuristically caches
    # the old bytes and — since the URL never changes — keeps showing the
    # previous portrait after an upload ("Photo uploaded" but nothing visibly
    # changes). "no-cache" lets the browser keep a copy but forces it to
    # revalidate with the server before reusing it, so a re-uploaded photo is
    # fetched fresh and the new portrait actually appears.
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


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
    chapters = outline_store.chapters_for(req.book)
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

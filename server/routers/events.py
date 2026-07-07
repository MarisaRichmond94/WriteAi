"""Timeline pane: enriched events + enrichment control (cost-gated)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3

from fastapi import APIRouter, HTTPException

from .. import audit, enrich
from ..canonical import Canonicalizer
from ..deps import get_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _titles(s) -> dict[int, str]:
    return dict(s.db.execute("SELECT DISTINCT book_number, book_title FROM chunks"))


_STOP = set(
    "the a an and or but of to in on at for with from by is was were are be "
    "been being he she it they them him his her hers their its i you we me my "
    "your our this that these those as not no so if then than there when while "
    "what who whom how why said says say had has have having did does do about "
    "into out up down over under after before just very".split())


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']{3,}", t.lower())} - _STOP


_ABBREV = {"Mr", "Mrs", "Ms", "Dr", "St", "Jr", "Sr", "Prof", "Lt", "Sgt", "Capt"}


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) spans of sentences, not splitting after honorifics."""
    spans, start = [], 0
    for m in re.finditer(r"[.!?…]+[\"'”’]*\s+|\n+", text):
        prev = re.search(r"([A-Za-z]+)$", text[:m.start()])
        if prev and prev.group(1) in _ABBREV:
            continue
        if text[start:m.end()].strip():
            spans.append((start, m.end()))
        start = m.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _relevant_excerpt(text: str, probe: str, max_len: int = 300) -> str:
    """The sentence run in `text` that best matches `probe` (event title +
    summary), as a contiguous verbatim slice snapped to sentence boundaries —
    still a substring of the chapter text, so the viewer can highlight it."""
    spans = _sentence_spans(text)
    if not spans:
        return text[:max_len]
    pw = _words(probe)
    best = max(range(len(spans)),
               key=lambda i: len(_words(text[spans[i][0]:spans[i][1]]) & pw))
    start, end = spans[best]
    # extend forward whole sentences while the budget allows
    j = best + 1
    while j < len(spans) and spans[j][1] - start <= max_len:
        end = spans[j][1]
        j += 1
    if end - start > max_len:  # single overlong sentence: cut at a word break
        cut = text.rfind(" ", start, start + max_len)
        end = cut if cut > start else start + max_len
    return text[start:end].strip()


# ── story-chronological ordering (ENABLE_STORY_ORDER) ───────────────────────
# chapter_timeline (populated by scripts/resolve_chronology.py) places every
# chapter at (story_year, month, day): story_year is a relative epoch shared
# across books, month/day parsed from the chapter's date line. Sorting by that
# triple puts flashback chapters where they belong in STORY time. The default
# narrative order is untouched — story order is opt-in via ?order=story.

# time-of-day cues seen in chunk metadata timeline_position, mapped to minutes
# since midnight; scanned in order so "early evening" wins over "evening".
_TOD_WORDS = [
    ("early morning", 7 * 60), ("late morning", 11 * 60), ("morning", 9 * 60),
    ("midday", 12 * 60), ("noon", 12 * 60), ("early afternoon", 13 * 60),
    ("late afternoon", 17 * 60), ("afternoon", 15 * 60),
    ("early evening", 18 * 60), ("late evening", 21 * 60), ("evening", 19 * 60),
    ("dusk", 18 * 60), ("sunset", 18 * 60), ("dawn", 6 * 60),
    ("sunrise", 6 * 60), ("midnight", 0), ("late night", 23 * 60),
    ("night", 21 * 60),
]

_CLOCK_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", re.IGNORECASE)


def _time_of_day_minutes(timeline_position: str | None) -> int | None:
    """Minutes since midnight from a timeline_position cue like
    'Saturday, October 31st, 2:00 PM' or '..., early evening'; None if the
    string carries no time-of-day."""
    if not timeline_position:
        return None
    m = _CLOCK_RE.search(timeline_position)
    if m:
        hour = int(m.group(1)) % 12
        if m.group(3).upper() == "PM":
            hour += 12
        return hour * 60 + int(m.group(2) or 0)
    low = timeline_position.lower()
    for word, minutes in _TOD_WORDS:
        if word in low:
            return minutes
    return None


def _chapter_timeline_map(db) -> dict[tuple[int, int], tuple]:
    """(book, chapter) -> (story_year, month, day, temporal_mode); empty when
    the table is absent or unpopulated (story order then unavailable)."""
    try:
        return {(b, c): (y, m, d, mode) for b, c, y, m, d, mode in db.execute(
            """SELECT book_number, chapter_number, story_year, month, day,
                      temporal_mode FROM chapter_timeline""")}
    except sqlite3.OperationalError:  # store predates the table
        return {}


def _apply_story_order(s, events: list[dict], meta: list[tuple],
                       timeline: dict[tuple[int, int], tuple]) -> list[dict]:
    """Annotate events with story_year/temporal_mode and sort them by
    (story_year, month, day, book, chapter, time-of-day, position). Events
    from chapters without a chapter_timeline row sort LAST, in narrative
    order. `meta` is index-aligned (book_number, chapter_number, position,
    first_source_chunk_id) for the events list."""
    # Time-of-day tie-break within a chapter, from the event's first source
    # chunk's timeline_position — only applied when EVERY event in that
    # chapter has a parsed time (partial times would reorder on no evidence).
    tods: dict[int, int | None] = {}
    by_chapter: dict[tuple[int, int], list[int]] = {}
    for i, (book, ch, _pos, first_cid) in enumerate(meta):
        row = s.db.execute(
            "SELECT json_extract(metadata_json, '$.timeline_position') "
            "FROM chunks WHERE chunk_id = ?", (first_cid,)).fetchone() \
            if first_cid else None
        tods[i] = _time_of_day_minutes(row[0]) if row else None
        by_chapter.setdefault((book, ch), []).append(i)
    tod_usable = {key: all(tods[i] is not None for i in idxs)
                  for key, idxs in by_chapter.items()}

    # Undated chapters (prologues; month/day NULL) sort just before the
    # nearest dated chapter of their book instead of at the epoch's front.
    sort_date: dict[tuple[int, int], tuple[float, float]] = {}
    per_book: dict[int, list[tuple[int, int | None, int | None]]] = {}
    for (b, ch), (_y, m, d, _mode) in timeline.items():
        per_book.setdefault(b, []).append((ch, m, d))
    for b, lst in per_book.items():
        lst.sort()
        for idx, (ch, m, d) in enumerate(lst):
            if m and d:
                sort_date[(b, ch)] = (m, d)
                continue
            near = next(((m2, d2) for _c, m2, d2 in lst[idx + 1:] if m2 and d2),
                        None) or next(((m2, d2) for _c, m2, d2
                                       in reversed(lst[:idx]) if m2 and d2), None)
            sort_date[(b, ch)] = (near[0], near[1] - 0.5) if near else (0, 0)

    def sort_key(i: int):
        book, ch, pos, _ = meta[i]
        placed = timeline.get((book, ch))
        if placed is None:
            return (1, book, ch, 0, 0, 0, pos)
        year = placed[0]
        month, day = sort_date[(book, ch)]
        tod = tods[i] if tod_usable[(book, ch)] else 0
        return (0, year, month, day, book, ch, tod or 0, pos)

    order = sorted(range(len(events)), key=sort_key)
    out = []
    for i in order:
        book, ch = meta[i][0], meta[i][1]
        placed = timeline.get((book, ch))
        out.append({**events[i],
                    "story_year": placed[0] if placed else None,
                    "temporal_mode": placed[3] if placed else None})
    return out


@router.get("/events/meta")
def events_meta():
    """Envelope-free /events stays a bare TimelineEvent[] for existing
    consumers; the UI asks here whether the story-order toggle applies
    (flag on AND chapter_timeline populated)."""
    s = get_state()
    return {"story_order_available":
            bool(getattr(s.cfg, "enable_story_order", False)
                 and _chapter_timeline_map(s.db))}


@router.get("/events")
def list_events(book: str | None = None, pov: str | None = None,
                granularity: str | None = None, order: str = "narrative"):
    """TimelineEvent[] in the UI's contract: book by NAME, verbatim source
    quotes (chunk excerpts — findable in the chapter text for highlighting),
    and cross-book setup hints from the source chunks' foreshadowing notes.

    order=story (with ENABLE_STORY_ORDER on and chapter_timeline populated)
    re-sorts into story-chronological order and adds story_year/temporal_mode
    per event; the default narrative order is byte-identical to before the
    flag existed."""
    s = get_state()
    enrich.ensure_tables(s.db)
    from .locations import resolved_map, resolved_map_v2
    loc_v2 = getattr(s.cfg, "enable_location_v2", False)
    loc_map = resolved_map_v2(s.db) if loc_v2 else resolved_map(s.db)
    titles = _titles(s)
    book_num = None
    if book:
        # number, exact title, or UI slug — punctuation-insensitive
        loose = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())
        book_num = int(book) if book.isdigit() else next(
            (n for n, t in titles.items() if loose(t) == loose(book)), None)

    clauses, params = [], []
    if book_num is not None:
        clauses.append("book_number = ?")
        params.append(book_num)
    if granularity:
        clauses.append("granularity = ?")
        params.append(granularity)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = s.db.execute(
        f"""SELECT id, book_number, chapter_number, position, title, type,
                   granularity, date_line, summary, location,
                   participants_json, knowledge_json, source_chunk_ids_json,
                   quote
            FROM events {where}
            ORDER BY book_number, chapter_number, position""", params).fetchall()
    s.canon.ensure_built()

    def is_named(p: str) -> bool:
        e = s.canon.entities.get(p)
        return e is not None and e.kind == "character"

    events = []
    meta = []  # index-aligned (book, chapter, position, first source chunk)
    for r in rows:
        participants = [p for p in json.loads(r[10] or "[]") if is_named(p)]
        if pov and pov not in participants:
            continue
        sources = json.loads(r[12] or "[]")
        curated = r[13]  # model-chosen quote, verified verbatim at enrich time
        source_quotes, setups = [], []
        loose_curated = re.sub(r"\s+", " ", curated).strip().lower() if curated else None
        for cid in sources[:3]:
            row = s.db.execute(
                "SELECT text, book_title, chapter_number, metadata_json "
                "FROM chunks WHERE chunk_id = ?", (cid,)).fetchone()
            if row is None:
                continue
            text = row[0].strip()
            if curated:
                # one curated quote, attributed to the chunk that contains it
                if not source_quotes and (loose_curated in
                        re.sub(r"\s+", " ", text).lower() or cid == sources[-1]):
                    source_quotes.append(
                        {"book": row[1], "chapter": row[2], "quote": curated})
            else:
                # fallback: sentence-aligned lexical excerpt
                quote = _relevant_excerpt(text, f"{r[4]} {r[8] or ''}")
                source_quotes.append({"book": row[1], "chapter": row[2], "quote": quote})
            if row[3]:
                setups.extend(json.loads(row[3]).get("foreshadowing", [])[:1])
        events.append({
            "id": str(r[0]),
            "title": r[4],
            "book": titles.get(r[1], f"Book {r[1]}"),
            "chapter": r[2],
            "date": r[7],
            "participants": participants,
            # normalized through the gazetteer: "Emma's house · Dead Falls";
            # unmappable raw locations show nothing (better none than bad)
            "location": (lambda pp: (f"{pp[0]} · {pp[1]}" if pp and pp[0] and pp[1]
                                     else pp[0] if pp else None))(
                            loc_map.get((r[1], r[9]) if loc_v2 else r[9]))
                        if r[9] else None,
            "type": r[5],
            "summary": r[8] or "",
            "granularity": r[6],
            "source_quotes": source_quotes,
            "knowledge_impact": json.loads(r[11] or "[]")[:6],
            "cross_book_setup": setups[0] if setups else None,
            "cross_book_payoff": None,
            "internal_year": None,
            "date_source": "extracted" if r[7] else None,
        })
        meta.append((r[1], r[2], r[3], sources[0] if sources else None))

    if order == "story" and getattr(s.cfg, "enable_story_order", False):
        timeline = _chapter_timeline_map(s.db)
        if timeline:  # unpopulated table -> narrative order, unchanged
            return _apply_story_order(s, events, meta, timeline)
    return events


@router.get("/enrich/preview")
def enrich_preview():
    s = get_state()
    return enrich.preview(s.db, s.cfg, s.canon)


@router.post("/enrich/run")
def enrich_run():
    s = get_state()
    if enrich.runner.running:
        audit.log_event("enrich_refused", "enrichment already running",
                        status=dict(enrich.runner.status))
        raise HTTPException(409, "enrichment already running")
    started = enrich.runner.start(
        s.cfg.sqlite_path, s.cfg,
        lambda db: Canonicalizer(db))
    audit.log_event("enrich_started", "enrichment run started",
                    started=started)
    return {"started": started}


@router.get("/enrich/status")
def enrich_status():
    return enrich.runner.status

"""Timeline pane: enriched events + enrichment control (cost-gated)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3

from fastapi import APIRouter, HTTPException

from .. import enrich
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


@router.get("/events")
def list_events(book: str | None = None, pov: str | None = None,
                granularity: str | None = None):
    """TimelineEvent[] in the UI's contract: book by NAME, verbatim source
    quotes (chunk excerpts — findable in the chapter text for highlighting),
    and cross-book setup hints from the source chunks' foreshadowing notes."""
    s = get_state()
    enrich.ensure_tables(s.db)
    from .locations import resolved_map
    loc_map = resolved_map(s.db)
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
                                     else pp[0] if pp else None))(loc_map.get(r[9]))
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
    return events


@router.get("/enrich/preview")
def enrich_preview():
    s = get_state()
    return enrich.preview(s.db, s.cfg, s.canon)


@router.post("/enrich/run")
def enrich_run():
    s = get_state()
    if enrich.runner.running:
        raise HTTPException(409, "enrichment already running")
    started = enrich.runner.start(
        s.cfg.sqlite_path, s.cfg,
        lambda db: Canonicalizer(db))
    return {"started": started}


@router.get("/enrich/status")
def enrich_status():
    return enrich.runner.status

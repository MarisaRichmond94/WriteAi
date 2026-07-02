"""Timeline pane: enriched events + enrichment control (cost-gated)."""

from __future__ import annotations

import json
import logging
import sqlite3

from fastapi import APIRouter, HTTPException

from .. import enrich
from ..canonical import Canonicalizer
from ..deps import get_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _titles(s) -> dict[int, str]:
    return dict(s.db.execute("SELECT DISTINCT book_number, book_title FROM chunks"))


@router.get("/events")
def list_events(book: str | None = None, pov: str | None = None,
                granularity: str | None = None):
    """TimelineEvent[] in the UI's contract: book by NAME, verbatim source
    quotes (chunk excerpts — findable in the chapter text for highlighting),
    and cross-book setup hints from the source chunks' foreshadowing notes."""
    s = get_state()
    enrich.ensure_tables(s.db)
    titles = _titles(s)
    book_num = None
    if book:
        book_num = int(book) if book.isdigit() else next(
            (n for n, t in titles.items() if t.lower() == book.lower()), None)

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
                   participants_json, knowledge_json, source_chunk_ids_json
            FROM events {where}
            ORDER BY book_number, chapter_number, position""", params).fetchall()
    events = []
    for r in rows:
        participants = json.loads(r[10] or "[]")
        if pov and pov not in participants:
            continue
        sources = json.loads(r[12] or "[]")
        source_quotes, setups = [], []
        for cid in sources[:3]:
            row = s.db.execute(
                "SELECT text, book_title, chapter_number, metadata_json "
                "FROM chunks WHERE chunk_id = ?", (cid,)).fetchone()
            if row is None:
                continue
            text = row[0].strip()
            # a verbatim opening excerpt — substring of the chapter text, so
            # the chapter viewer can locate and highlight it
            quote = text[:280]
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
            "location": r[9],
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

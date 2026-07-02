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


@router.get("/events")
def list_events(book: int | None = None, participant: str | None = None,
                granularity: str | None = None):
    s = get_state()
    enrich.ensure_tables(s.db)
    clauses, params = [], []
    if book is not None:
        clauses.append("book_number = ?")
        params.append(book)
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
        if participant and participant not in participants:
            continue
        events.append({
            "id": r[0], "book_number": r[1], "chapter_number": r[2],
            "position": r[3], "title": r[4], "type": r[5], "granularity": r[6],
            "date": r[7], "summary": r[8], "location": r[9],
            "participants": participants,
            "knowledge_impact": json.loads(r[11] or "[]"),
            "source_chunk_ids": json.loads(r[12] or "[]"),
        })
    return {"events": events, "enriched": bool(rows) or None}


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

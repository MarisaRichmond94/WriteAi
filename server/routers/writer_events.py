"""Writer-authored timeline events — the writer's version of the Events page.

These are events the writer creates by hand as part of the writing process,
kept entirely separate from the AI-extracted `events` table. They live in
writer_data/writer_events.json (via writer_store) and are never touched by AI.

Each event may tag writer characters, a writer-created location, and any number
of book+chapter pairs. The location pool is stored alongside the events so the
form can offer "select an existing location" without re-deriving it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import loom_client, writer_store

router = APIRouter(prefix="/api")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BookChapterTag(BaseModel):
    book: str
    chapter: int


class WriterEventBody(BaseModel):
    title: str = ""
    date: str | None = None
    time: str | None = None
    description: str = ""
    characters: list[str] = []
    location: str | None = None
    book_chapters: list[BookChapterTag] = []


class LocationBody(BaseModel):
    name: str


def _add_location(store: dict, name: str | None) -> None:
    """Fold a location into the pool (case-preserving, de-duplicated)."""
    if not name:
        return
    name = name.strip()
    if name and name not in store["locations"]:
        store["locations"].append(name)


@router.get("/writer-events/chapter-links")
def writer_event_chapter_links(ids: str = ""):
    """Which Loom chapters reference these events (LOOM-32).

    The reverse of the tagging Loom's Events tab does. Loom owns the join —
    keyed there by chapter cuid, which is what makes a tag survive a chapter
    being inserted above it — so only Loom can answer, and this is a
    pass-through rather than a second source of truth.

    Deliberately NOT cached. A stale answer is worse than no answer here: the
    point of the seam is that these numbers track Loom, and a mirror would
    quietly reintroduce the drift the epic exists to remove. Loom being closed
    is a state the UI names, not one it papers over.

    Loom returns the rows already denormalised (series, book, chapter, number,
    path), so nothing is re-resolved here. `readPath` is RELATIVE — Loom has no
    reliable way to know its own external origin, and the frontend already
    configures VITE_LOOM_URL for its existing jump links.

    Declared before /writer-events/{event_id} so the literal path wins.
    """
    ids = ids.strip()
    if not ids:
        return {}
    try:
        return loom_client.get_json(f"/api/chapter-events?eventIds={quote(ids)}")
    except loom_client.LoomUnreachable as exc:
        # 503, not 502: nothing is broken, Loom is simply not running.
        return JSONResponse(
            status_code=503,
            content={"error": "Loom is not reachable", "unreachable": True, "detail": str(exc)},
        )


@router.get("/writer-events")
def list_writer_events():
    store = writer_store.writer_events()
    # Newest first — writers work at the growing edge of the story.
    events = sorted(store["events"], key=lambda e: e.get("created_at", ""), reverse=True)
    return {"events": events, "locations": sorted(store["locations"], key=str.lower)}


@router.post("/writer-events")
def create_writer_event(body: WriterEventBody):
    store = writer_store.writer_events()
    now = _now()
    event = {
        "id": f"we-{uuid.uuid4().hex[:8]}",
        "title": body.title.strip(),
        "date": body.date,
        "time": body.time,
        "description": body.description,
        "characters": body.characters,
        "location": (body.location or "").strip() or None,
        "book_chapters": [bc.model_dump() for bc in body.book_chapters],
        "created_at": now,
        "updated_at": now,
    }
    store["events"].append(event)
    _add_location(store, event["location"])
    writer_store.save_writer_events(store)
    return event


@router.patch("/writer-events/{event_id}")
def update_writer_event(event_id: str, body: WriterEventBody):
    store = writer_store.writer_events()
    event = next((e for e in store["events"] if e["id"] == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    event.update({
        "title": body.title.strip(),
        "date": body.date,
        "time": body.time,
        "description": body.description,
        "characters": body.characters,
        "location": (body.location or "").strip() or None,
        "book_chapters": [bc.model_dump() for bc in body.book_chapters],
        "updated_at": _now(),
    })
    _add_location(store, event["location"])
    writer_store.save_writer_events(store)
    return event


@router.delete("/writer-events/{event_id}")
def delete_writer_event(event_id: str):
    store = writer_store.writer_events()
    before = len(store["events"])
    store["events"] = [e for e in store["events"] if e["id"] != event_id]
    if len(store["events"]) == before:
        raise HTTPException(status_code=404, detail="Event not found")
    writer_store.save_writer_events(store)
    return {"ok": True}


@router.post("/writer-events/locations")
def add_writer_location(body: LocationBody):
    store = writer_store.writer_events()
    _add_location(store, body.name)
    writer_store.save_writer_events(store)
    return {"locations": sorted(store["locations"], key=str.lower)}

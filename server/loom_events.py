"""Loom event consumer: near-real-time index sync.

Polls Loom's event outbox (GET {LOOM_URL}/api/events?since=<cursor>) and,
once a book's canon exports have been quiet for a debounce window, triggers
the same incremental ingest the Resync button uses. Only export.completed
is acted on — it is Loom's "a consistent canon snapshot is on disk" signal;
chapter.created / chapter.deleted events always precede one.

Loom being unreachable is normal (the author isn't writing, or the app is
closed): the cursor just waits. The nightly scheduler and the manifest
drift check (/api/sync/status) remain the reconciliation safety net for
anything events miss.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request

from fastapi import HTTPException

from src.discovery import discover_books

from . import audit, writer_store
from .deps import get_state
from .routers.books import ingest_run
from .writer_store import WRITER_DATA_DIR

log = logging.getLogger(__name__)

LOOM_URL = os.environ.get("LOOM_URL", "http://localhost:3000")
_POLL_SECONDS = 120
# A writing session produces an export per blur/chapter-switch; waiting for
# a quiet stretch turns that stream into one ingest at the session's end.
_DEBOUNCE_SECONDS = 600

_CURSOR_PATH = WRITER_DATA_DIR / "loom_event_cursor.json"

_pending: dict[str, float] = {}  # book title -> monotonic time of last event
_was_reachable = True


def _read_cursor() -> int:
    try:
        return int(json.loads(_CURSOR_PATH.read_text())["cursor"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return 0


def _write_cursor(seq: int) -> None:
    WRITER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CURSOR_PATH.write_text(json.dumps({"cursor": seq}))


def _fetch_events(cursor: int) -> dict | None:
    try:
        with urllib.request.urlopen(
                f"{LOOM_URL}/api/events?since={cursor}", timeout=10) as res:
            return json.load(res)
    except (urllib.error.URLError, OSError, ValueError):
        return None


async def _tick() -> None:
    global _was_reachable
    # Same switch as the nightly scheduler: turning auto-sync off freezes
    # EVERY automatic index write — required during RAG eval runs, where a
    # concurrent ingest's SQLite writes contend with eval reads. The cursor
    # still advances-on-resume, so nothing is lost while paused.
    if not writer_store.ui_settings().get("auto_sync_enabled"):
        return
    # First run ever: adopt the current tip without acting on history —
    # whatever those old exports changed is already covered by the manifest
    # drift check and the nightly reconcile.
    first_run = not _CURSOR_PATH.exists()
    cursor = _read_cursor()
    data = await asyncio.to_thread(_fetch_events, cursor)
    if data is None:
        if _was_reachable:
            log.info("loom-events: %s unreachable — retrying quietly", LOOM_URL)
            _was_reachable = False
    else:
        if not _was_reachable:
            log.info("loom-events: %s reachable again", LOOM_URL)
            _was_reachable = True
        if first_run:
            _write_cursor(data.get("cursor", cursor))
            return
        for event in data.get("events", []):
            if event.get("type") != "export.completed":
                continue
            title = (event.get("payload") or {}).get("bookTitle")
            if title:
                _pending[title] = time.monotonic()
        if data.get("cursor", cursor) != cursor:
            _write_cursor(data["cursor"])

    now = time.monotonic()
    due = [t for t, at in _pending.items() if now - at >= _DEBOUNCE_SECONDS]
    if not due:
        return
    numbers = {b.title: b.number for b in discover_books(get_state().cfg)}
    for title in due:
        number = numbers.get(title)
        if number is None:
            log.warning("loom-events: no folder matches exported book %r — dropping", title)
            _pending.pop(title, None)
            continue
        try:
            ingest_run(book=number)
        except HTTPException:
            # an ingest is already running — keep pending, retry next tick
            return
        _pending.pop(title, None)
        audit.log_event("loom_event_sync",
                        f"auto-ingest of '{title}' after Loom canon export",
                        book=number)


async def run_forever() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("loom-events: tick failed")
        await asyncio.sleep(_POLL_SECONDS)

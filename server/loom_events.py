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
import time
import urllib.error
import urllib.request

from fastapi import HTTPException

from src.discovery import discover_books

from . import audit, writer_store
from .deps import get_state
from .loom_client import LOOM_URL
from .routers.books import ingest_run
from .writer_store import WRITER_DATA_DIR

log = logging.getLogger(__name__)

_POLL_SECONDS = 120
# A writing session produces an export per blur/chapter-switch; waiting for
# a quiet stretch turns that stream into one ingest at the session's end.
_DEBOUNCE_SECONDS = 600
# Structural changes get a much shorter wait. Ten minutes is the right answer
# for prose, which arrives as a stream of small edits worth batching — but a
# chapter being added or removed is a discrete act that happens once,
# renumbers the rest of the book, and leaves the index confidently wrong
# about every chapter below it until it lands. There is nothing to batch.
_STRUCTURAL_DEBOUNCE_SECONDS = 60

_CURSOR_PATH = WRITER_DATA_DIR / "loom_event_cursor.json"

_pending: dict[str, float] = {}  # book title -> monotonic time of last event
# Books whose pending export followed a chapter being created or deleted,
# keyed by title like _pending and cleared once the book is ingested.
_structural: set[str] = set()
# Loom book cuids seen in a chapter.created/deleted whose export.completed
# has not arrived yet. Those events carry a bookId and no book TITLE, and
# _pending is keyed by title — export.completed carries both, so it is the
# export that resolves one to the other. Loom emits the structural event
# first and the export immediately after, so the two normally land in the
# same poll; holding the id across polls covers the case where they don't.
_structural_book_ids: set[str] = set()
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
            payload = event.get("payload") or {}
            kind = event.get("type")
            # Still only export.completed triggers an ingest — it is the
            # "a consistent canon snapshot is on disk" signal, and nothing
            # else is safe to read. chapter.created/deleted only mark the
            # book, so the export that follows is treated as urgent.
            if kind in ("chapter.created", "chapter.deleted"):
                if payload.get("bookId"):
                    _structural_book_ids.add(payload["bookId"])
                continue
            if kind != "export.completed":
                continue
            title = payload.get("bookTitle")
            if title:
                _pending[title] = time.monotonic()
                if payload.get("bookId") in _structural_book_ids:
                    _structural_book_ids.discard(payload["bookId"])
                    _structural.add(title)
        if data.get("cursor", cursor) != cursor:
            _write_cursor(data["cursor"])

    now = time.monotonic()
    due = [t for t, at in _pending.items()
           if now - at >= (_STRUCTURAL_DEBOUNCE_SECONDS if t in _structural
                           else _DEBOUNCE_SECONDS)]
    if not due:
        return
    numbers = {b.title: b.number for b in discover_books(get_state().cfg)}
    resolved = []
    for title in due:
        number = numbers.get(title)
        if number is None:
            log.warning("loom-events: no folder matches exported book %r — dropping", title)
            _pending.pop(title, None)
            _structural.discard(title)
            continue
        resolved.append((title, number))
    if not resolved:
        return
    # Coalesce a burst that spans multiple books into a single incremental
    # all-books run: one subprocess and one post-ingest write pass instead of
    # one per book (previously spread one-per-tick), which minimises how often
    # an ingest writer overlaps a concurrent DB writer. A lone due book still
    # runs scoped, since its diff is cheaper.
    scope_book = resolved[0][1] if len(resolved) == 1 else None
    try:
        ingest_run(book=scope_book)
    except HTTPException:
        # an ingest (or its post-processing) is in progress — keep every due
        # book pending and retry on the next tick.
        return
    for title, number in resolved:
        _pending.pop(title, None)
        was_structural = title in _structural
        _structural.discard(title)
        audit.log_event(
            "loom_event_sync",
            f"auto-ingest of '{title}' after Loom canon export"
            + (" (chapter added or removed)" if was_structural else ""),
            book=number)


async def run_forever() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("loom-events: tick failed")
        await asyncio.sleep(_POLL_SECONDS)

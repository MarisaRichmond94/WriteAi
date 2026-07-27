"""Nightly ingest scheduler.

Checks the writer's configured sync time (Settings -> Sync) once a minute
and, when it's due, kicks off a full re-ingest via the same code path as
the manual Resync button (POST /api/ingest/run). At most one automatic
run per UTC calendar day.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from . import writer_store
from .routers.books import ingest_run

log = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60

_last_run_date: str | None = None


def _enrich_due_today(now: datetime, freq: str) -> bool:
    """Whether an enrichment run should piggyback tonight's nightly sync,
    given the writer's cadence (Settings -> Sync). Weekly-and-longer cadences
    fire on Sundays so the run lands on a predictable day. Derived purely from
    the date, so it needs no persisted bookkeeping and survives restarts."""
    if freq == "daily":
        return True
    if now.weekday() != 6:  # Monday=0 .. Sunday=6; anchor to Sunday
        return False
    if freq == "weekly":
        return True
    if freq == "biweekly":
        return now.isocalendar()[1] % 2 == 0  # every other ISO week
    if freq == "monthly":
        return now.day <= 7  # the month's first Sunday
    return False


async def _tick() -> None:
    global _last_run_date
    profile = writer_store.ui_settings()
    if not profile.get("auto_sync_enabled"):
        return
    sync_time = profile.get("sync_time")
    if not sync_time:
        return

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if today == _last_run_date or now.strftime("%H:%M") != sync_time:
        return

    _last_run_date = today
    # Enrichment rides the nightly sync, but only on days the writer's cadence
    # is due — so daily/weekly/biweekly/monthly all bill one batched run at
    # most, never per incremental sync. Independently of this, any sync that
    # adds or removes a chapter forces a run (see _watch in routers/books.py),
    # because renumbering strands every downstream summary on the wrong
    # chapter and that is visible on the plan page right away.
    enrich_after = bool(profile.get("auto_enrich_enabled")) and _enrich_due_today(
        now, profile.get("enrich_frequency", "daily"))
    log.info("nightly sync: sync_time=%s UTC reached, starting scheduled re-ingest "
             "(enrich=%s)", sync_time, enrich_after)
    try:
        ingest_run(book=None, enrich_after=enrich_after)
    except HTTPException as e:
        # 409: an ingest (manual or scheduled) is already running — fine, skip tonight.
        log.info("nightly sync: skipped (%s)", e.detail)
    except Exception:
        log.exception("nightly sync: failed to start scheduled ingest")


async def run_forever() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("nightly sync: scheduler tick failed")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)

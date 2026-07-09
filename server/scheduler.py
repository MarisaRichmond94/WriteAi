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
    log.info("nightly sync: sync_time=%s UTC reached, starting scheduled re-ingest", sync_time)
    try:
        ingest_run(book=None)
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

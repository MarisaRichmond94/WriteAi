"""FastAPI app for the series-RAG web UI.

    .venv/bin/uvicorn server.main:app --port 8000

Serves /api/* plus the built frontend (frontend/dist) when present.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import REPO_ROOT

from . import loom_events, scheduler
from .routers import (books, characters, chat, events, locations,
                      notifications, plan, review, sessions, settings,
                      sync, writer_events)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")


@asynccontextmanager
async def lifespan(app: FastAPI):
    nightly = asyncio.create_task(scheduler.run_forever())
    loom = asyncio.create_task(loom_events.run_forever())
    yield
    nightly.cancel()
    loom.cancel()

app = FastAPI(title="Series RAG", docs_url="/api/docs", openapi_url="/api/openapi.json",
              lifespan=lifespan)

app.add_middleware(  # dev server on :5173 talks to us directly
    CORSMiddleware, allow_origins=["http://localhost:5173"],
    allow_methods=["*"], allow_headers=["*"])

for r in (books, chat, review, characters, events, locations,
          notifications, plan, sessions, settings, sync, writer_events):
    app.include_router(r.router)

dist = REPO_ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

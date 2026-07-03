"""FastAPI app for the series-RAG web UI.

    .venv/bin/uvicorn server.main:app --port 8000

Serves /api/* plus the built frontend (frontend/dist) when present.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import REPO_ROOT

from .routers import (books, characters, chat, events, locations,
                      notifications, plan, review, sessions, settings)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

app = FastAPI(title="Series RAG", docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(  # dev server on :5173 talks to us directly
    CORSMiddleware, allow_origins=["http://localhost:5173"],
    allow_methods=["*"], allow_headers=["*"])

for r in (books, chat, review, characters, events, locations,
          notifications, plan, sessions, settings):
    app.include_router(r.router)

dist = REPO_ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

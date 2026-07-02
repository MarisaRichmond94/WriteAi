"""Explore-chat and review session history, persisted in writer_data.

Sessions are stored verbatim as the frontend shapes them (messages,
citations, timestamps as ISO strings) so a reload — or another browser —
can restore the sidebar history exactly.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from .. import writer_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_KINDS = ("chat", "review")


def _sessions() -> dict:
    d = writer_store.load("sessions.json", {})
    for k in _KINDS:
        d.setdefault(k, [])
    return d


@router.get("/sessions")
def list_sessions():
    return _sessions()


@router.put("/sessions/{kind}/{sid}")
def upsert_session(kind: str, sid: str, body: dict):
    if kind not in _KINDS:
        raise HTTPException(400, f"unknown session kind: {kind}")
    d = _sessions()
    body["id"] = sid
    entries = d[kind]
    for i, s in enumerate(entries):
        if s.get("id") == sid:
            entries[i] = body
            break
    else:
        entries.append(body)
    writer_store.save("sessions.json", d)
    return {"ok": True}


@router.delete("/sessions/{kind}/{sid}")
def delete_session(kind: str, sid: str):
    if kind not in _KINDS:
        raise HTTPException(400, f"unknown session kind: {kind}")
    d = _sessions()
    d[kind] = [s for s in d[kind] if s.get("id") != sid]
    writer_store.save("sessions.json", d)
    return {"ok": True}

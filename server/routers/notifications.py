"""Notification inbox for the bell: create, list, mark read, delete."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import audit, notify, writer_store

router = APIRouter(prefix="/api")


class NotificationCreate(BaseModel):
    type: str
    title: str
    body: str
    book: str | None = None
    action_url: str | None = None


@router.post("/notifications")
def create_notification(payload: NotificationCreate):
    """UI-originated events (e.g. the review deep link's sync check) land in
    the same inbox as the backend's job notifications — and in the audit
    trail, so user-visible errors are traceable after the fact."""
    notify.add(payload.type, payload.title, payload.body,
               book=payload.book, action_url=payload.action_url)
    audit.log_event(f"notification_{payload.type}", payload.title,
                    body=payload.body, book=payload.book, source="ui")
    return {"ok": True}


class AuditEvent(BaseModel):
    kind: str
    message: str
    fields: dict = {}


@router.post("/audit")
def audit_event(payload: AuditEvent):
    """Client-side breadcrumbs (poll timeouts, queued retries, fetch
    failures) — things worth tracing that don't warrant a bell entry."""
    audit.log_event(payload.kind, payload.message, source="ui",
                    **payload.fields)
    return {"ok": True}


@router.get("/notifications")
def list_notifications():
    items = writer_store.load("notifications.json", [])
    return list(reversed(items))  # newest first


@router.post("/notifications/read-all")
def mark_all_read():
    items = writer_store.load("notifications.json", [])
    for n in items:
        n["read"] = True
    writer_store.save("notifications.json", items)
    return {"ok": True}


@router.post("/notifications/{nid}/read")
def mark_read(nid: str):
    items = writer_store.load("notifications.json", [])
    for n in items:
        if n.get("id") == nid:
            n["read"] = True
    writer_store.save("notifications.json", items)
    return {"ok": True}


@router.delete("/notifications")
def clear_all_notifications():
    """Empty the inbox — backs the bell's 'Clear all' button."""
    writer_store.save("notifications.json", [])
    return {"ok": True}


@router.delete("/notifications/{nid}")
def delete_notification(nid: str):
    items = writer_store.load("notifications.json", [])
    writer_store.save("notifications.json",
                      [n for n in items if n.get("id") != nid])
    return {"ok": True}

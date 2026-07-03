"""Notification inbox for the bell: list, mark read, delete."""

from __future__ import annotations

from fastapi import APIRouter

from .. import writer_store

router = APIRouter(prefix="/api")


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


@router.delete("/notifications/{nid}")
def delete_notification(nid: str):
    items = writer_store.load("notifications.json", [])
    writer_store.save("notifications.json",
                      [n for n in items if n.get("id") != nid])
    return {"ok": True}

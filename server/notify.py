"""UI notifications, persisted in writer_data/notifications.json.

Emitted by long-running jobs (ingest, enrichment) and polled by the
notification bell. Kept to the newest 50.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from . import writer_store

_MAX = 50


def add(type_: str, title: str, body: str, book: str | None = None,
        action_url: str | None = None) -> None:
    items = writer_store.load("notifications.json", [])
    items.append({
        "id": uuid.uuid4().hex[:12],
        "type": type_,
        "title": title,
        "body": body,
        "book": book,
        "created_at": datetime.now().isoformat(),
        "read": False,
        "action_url": action_url,
    })
    writer_store.save("notifications.json", items[-_MAX:])

"""Append-only audit trail: logs/audit.jsonl.

One JSON line per pipeline/UI event (sync started or refused, enrichment
queued or failed, client-side errors, …) with a timestamp and free-form
fields — the first place to look when something like "Enrichment failed to
start" needs tracing after the fact. Every event is mirrored to the server
log so it also shows up live in the uvicorn console.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from config import REPO_ROOT

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_PATH = REPO_ROOT / "logs" / "audit.jsonl"


def log_event(kind: str, message: str, **fields) -> None:
    """Best-effort: an audit failure must never break the operation it
    describes."""
    entry = {"at": datetime.now().isoformat(), "kind": kind,
             "message": message, **fields}
    log.info("audit[%s]: %s%s", kind, message,
             f" {fields}" if fields else "")
    try:
        with _LOCK:
            _PATH.parent.mkdir(exist_ok=True)
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("audit write to %s failed", _PATH, exc_info=True)

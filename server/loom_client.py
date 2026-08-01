"""Talking to Loom.

Loom and WriteAI are separate apps coupled through the filesystem and a
couple of read-only HTTP calls (see INTEGRATION.md). This holds the pieces
both directions of that seam need, so LOOM_URL has exactly one definition —
two copies reading the same env var is how a base URL ends up configured in
one place and not the other.

Deliberately thin: urllib rather than a client library, because the server
already depends on nothing else for this and the calls are two GETs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

LOOM_URL = os.environ.get("LOOM_URL", "http://localhost:3000")


class LoomUnreachable(Exception):
    """Loom is not running, or did not answer in time.

    A normal condition, not a fault: the writer may simply not have Loom
    open. Callers surface it as its own state rather than as an error —
    an empty result would claim "no chapters reference this", which is a
    different and much more misleading statement.
    """


def get_json(path: str, timeout: int = 10):
    """GET a JSON document from Loom, or raise LoomUnreachable."""
    try:
        with urllib.request.urlopen(f"{LOOM_URL}{path}", timeout=timeout) as res:
            return json.load(res)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LoomUnreachable(str(exc)) from exc

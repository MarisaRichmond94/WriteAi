"""Server-sent-events helper: the reference app's wire format.

Every AI stream emits:
    data: {"type": "chunk", "content": "..."}        (many)
    data: {"type": "citations", "sources": [...]}     (once, optional)
    data: {"type": "usage", ...}                      (once, optional)
    data: {"type": "done"}                            (always last)
    data: {"type": "error", "message": "..."}         (on failure)
"""

from __future__ import annotations

import json
import logging

from fastapi.responses import StreamingResponse

log = logging.getLogger(__name__)


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_response(generator) -> StreamingResponse:
    """Wrap a generator of payload dicts as an SSE response, guaranteeing a
    terminal done/error event even when the generator raises."""

    def wrapped():
        try:
            for payload in generator:
                yield _event(payload)
        except Exception as e:  # surface, never hang the client
            log.exception("stream failed")
            yield _event({"type": "error", "message": str(e)})
        yield _event({"type": "done"})

    return StreamingResponse(wrapped(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def citations_payload(excerpts: list[dict]) -> dict:
    return {"type": "citations", "sources": [
        {"chunk_id": e["chunk_id"],
         "book_number": e.get("book_number"),
         "book_title": e.get("book_title"),
         "chapter_number": e.get("chapter_number"),
         "pov_character": e.get("pov_character"),
         "distance": e.get("distance"),
         "preview": (e.get("text") or "")[:180]}
        for e in excerpts]}

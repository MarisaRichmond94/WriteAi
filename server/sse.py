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
    """Citation shape the UI's citation cards render: book name, chapter,
    POV, snippet, distance (plus chunk_id so the source viewer can open the
    exact passage)."""
    sources = []
    for e in excerpts:
        chunk_index = 0
        cid = e.get("chunk_id") or ""
        if ".k" in cid:
            try:
                chunk_index = int(cid.rsplit(".k", 1)[1])
            except ValueError:
                pass
        sources.append({
            "book": e.get("book_title") or f"Book {e.get('book_number')}",
            "chapter": e.get("chapter_number") or 0,
            "chapter_heading": f"Chapter {e.get('chapter_number')}",
            "pov": e.get("pov_character") or "",
            "date": None,
            "chunk_index": chunk_index,
            "snippet": (e.get("text") or "")[:220],
            "distance": e.get("distance") if e.get("distance") is not None else 0.5,
            "chunk_id": e.get("chunk_id"),
        })
    return {"type": "citations", "sources": sources}

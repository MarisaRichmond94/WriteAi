"""Server-sent-events helper: the reference app's wire format.

Every AI stream emits:
    data: {"type": "chunk", "content": "..."}        (many)
    data: {"type": "notice", "message": "..."}        (optional, before chunks)
    data: {"type": "citations", "sources": [...]}     (once, optional)
    data: {"type": "usage", ...}                      (once, optional)
    data: {"type": "done"}                            (always last)
    data: {"type": "error", "message": "..."}         (on failure)

A `notice` reports that the answer is degraded but real — retrieval fell over
and the model worked from thinner context, say. `error` means there is no
answer at all.
"""

from __future__ import annotations

import json
import logging

from fastapi.responses import StreamingResponse

log = logging.getLogger(__name__)


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _loom_ids_by_book_number() -> dict[int, tuple[str | None, str | None]]:
    """book_number -> (loom_book_id, loom_series_id) for citation deep links.

    Resolved from the manifest sidecars (KAN-12) rather than threaded through
    retrieval: those queries return positional tuples unpacked in three places,
    so widening their column lists would be a far larger and riskier change
    than looking the ids up here.

    Never raises. Citations must render even when identity is unresolvable —
    the UI falls back to title-addressed links.
    """
    try:
        from src.discovery import discover_books

        from .deps import get_state
        return {b.number: (b.loom_book_id, b.loom_series_id)
                for b in discover_books(get_state().cfg)}
    except Exception:
        log.warning("could not resolve Loom ids for citations — deep links "
                    "fall back to title addressing", exc_info=True)
        return {}


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
    exact passage). `text` carries the full chunk so the card can quote-match
    and sentence-snap; `snippet` stays as the legacy 220-char prefix."""
    loom_ids = _loom_ids_by_book_number()
    sources = []
    for e in excerpts:
        loom_book_id, loom_series_id = loom_ids.get(e.get("book_number"), (None, None))
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
            "text": e.get("text") or "",
            "distance": e.get("distance") if e.get("distance") is not None else 0.5,
            "chunk_id": e.get("chunk_id"),
            # Stable identity for the Loom deep link (KAN-12). Null when the
            # book has never been canon-exported; the card then falls back to
            # the title-addressed route.
            "loom_book_id": loom_book_id,
            "loom_series_id": loom_series_id,
        })
    return {"type": "citations", "sources": sources}

"""Explore pane: streaming RAG chat over the existing query layer."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from src.query_router import Scope, classify

from ..deps import get_state
from ..sse import citations_payload, stream_response

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# UI query modes -> internal query types
MODE_MAP = {
    "plot_hole": "continuity",
    "timeline": "temporal_knowledge",
    "character": "sentiment",
    "alternate": "general",
    "general": None,  # let the router auto-classify
}

ALTERNATE_EXTRA = (
    "The author is exploring an alternate scenario ('what if...'). Ground your "
    "reasoning in what the excerpts establish about the characters and world, "
    "clearly separating canon facts (cited) from speculation."
)


class ChatRequest(BaseModel):
    message: str
    mode: str = "general"
    book_filter: list[str | int] = []
    pov_filter: list[str] = []
    conversation_history: list[dict] = []


@router.post("/chat/stream")
def chat_stream(req: ChatRequest):
    s = get_state()

    def resolve_books(values):
        titles = {t.lower(): n for n, t in s.db.execute(
            "SELECT DISTINCT book_number, book_title FROM chunks")}
        out = []
        for v in values:
            if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
                out.append(int(v))
            elif isinstance(v, str) and v.lower() in titles:
                out.append(titles[v.lower()])
        return out

    def generate():
        books = resolve_books(req.book_filter)
        plan = classify(req.message,
                        forced_type=MODE_MAP.get(req.mode) or None)
        if books:
            plan.scope = Scope(book_min=min(books), book_max=max(books))
        excerpts, notes = s.retriever.retrieve(plan)
        # exact-set filters the range scope can't express
        if books:
            excerpts = [e for e in excerpts
                        if e.get("book_number") in set(books)]
        if req.pov_filter:
            povs = set(req.pov_filter)
            filtered = [e for e in excerpts if e.get("pov_character") in povs]
            if filtered:  # don't starve the model if the filter is too tight
                excerpts = filtered

        answerer = s.new_answerer()
        history = [{"role": m["role"], "content": m["content"]}
                   for m in req.conversation_history[-8:]
                   if m.get("role") in ("user", "assistant") and m.get("content")]

        extra = ALTERNATE_EXTRA if req.mode == "alternate" else ""
        for delta in answerer.answer_stream(plan, excerpts, notes,
                                            history=history, system_extra=extra):
            yield {"type": "chunk", "content": delta}
        yield citations_payload(excerpts)
        yield {"type": "usage", "model": answerer.model,
               "input_tokens": answerer.usage["input_tokens"],
               "output_tokens": answerer.usage["output_tokens"],
               "cost_usd": answerer.actual_cost_usd}

    return stream_response(generate())

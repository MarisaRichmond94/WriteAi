"""Explore pane: streaming RAG chat over the existing query layer."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter
from pydantic import BaseModel

from src.answerer import ALTERNATE_SYSTEM
from src.costlog import log_cost, usage_diff
from src.query_router import Scope, classify

from ..deps import get_state
from ..sse import citations_payload, stream_response
from .books import _build_bible

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

class ChatRequest(BaseModel):
    message: str
    mode: str = "general"
    book_filter: list[str | int] = []
    pov_filter: list[str] = []
    conversation_history: list[dict] = []
    model: str | None = None          # per-request model (None = settings default)


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

        answerer = s.new_answerer(model=req.model)
        history = [{"role": m["role"], "content": m["content"]}
                   for m in req.conversation_history[-8:]
                   if m.get("role") in ("user", "assistant") and m.get("content")]

        extra_parts = []
        bible_parts = []
        for book_num in books:
            try:
                _, md = _build_bible(s, book_num, compact=True)
                bible_parts.append(md)
            except Exception:
                log.warning("could not build bible for book %s", book_num)
        if bible_parts:
            extra_parts.append(
                "The following condensed story bibles cover the books the "
                "author has in scope — major characters plus a chapter-by-"
                "chapter summary of each book. Use them for overarching, "
                "cross-book questions; the retrieved excerpts remain the "
                "source of truth for verbatim detail.\n\n"
                + "\n\n---\n\n".join(bible_parts))
        extra = "\n\n".join(extra_parts)
        # "what-if" mode swaps in a speculation-friendly base prompt instead of
        # the default "answer only from the text" one; None keeps the default.
        system_base = ALTERNATE_SYSTEM if req.mode == "alternate" else None
        u0, c0, t0 = dict(answerer.usage), answerer.actual_cost_usd, time.monotonic()
        for delta in answerer.answer_stream(plan, excerpts, notes,
                                            history=history, system_extra=extra,
                                            system_base=system_base):
            yield {"type": "chunk", "content": delta}
        log_cost(s.cfg, surface="chat", model=answerer.model, qtype=plan.qtype,
                 usage=usage_diff(answerer.usage, u0),
                 cost_usd=round(answerer.actual_cost_usd - c0, 4),
                 latency_ms=int((time.monotonic() - t0) * 1000),
                 extra={"mode": req.mode})
        yield citations_payload(excerpts)
        u = answerer.usage
        yield {"type": "usage", "model": answerer.model,
               # full prompt size — cached tokens included, cost already
               # reflects their discounted (or premium write) rates
               "input_tokens": (u["input_tokens"] + u["cache_write_tokens"]
                                + u["cache_read_tokens"]),
               "output_tokens": u["output_tokens"],
               # cache breakdown so the UI (and anyone watching the SSE
               # stream) can see whether the prompt cache is engaging
               "cache_write_tokens": u["cache_write_tokens"],
               "cache_read_tokens": u["cache_read_tokens"],
               "cost_usd": answerer.actual_cost_usd}

    return stream_response(generate())

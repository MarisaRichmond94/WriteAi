"""Review pane: focused AI feedback on a chapter (synced or pasted draft)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.query_router import QueryPlan, Scope

from ..deps import get_state
from ..sse import citations_payload, stream_response

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

FOCUS_PROMPTS = {
    "Rough Draft": (
        "You are giving first-read feedback on a rough draft chapter: overall "
        "impressions, what lands, what confuses, the 2-3 highest-impact "
        "improvements. Encourage, but be concrete."),
    "Continuity": (
        "You are checking this chapter against the rest of the series for "
        "continuity: contradictions with established facts, character knowledge "
        "violations (someone knowing what they can't yet know), timeline "
        "problems, and dropped threads. Cite (Book N, Chapter M) for every "
        "conflict you flag."),
    "Character Voice": (
        "You are evaluating character voice: does each character sound like "
        "themselves as established across the series? Flag lines that feel "
        "off-voice and explain what their established voice would do, citing "
        "supporting scenes."),
    "Line Edit": (
        "You are line-editing: prose rhythm, word repetition, filter words, "
        "dialogue tags, sentence variety. Quote specific lines and offer "
        "rewrites. Do not restructure the story."),
    "Pacing": (
        "You are analyzing pacing: where the chapter drags or rushes, scene/"
        "sequel balance, tension curve, and where beats could be tightened or "
        "expanded."),
}


class ReviewRequest(BaseModel):
    book: int
    chapter: int | None = None        # synced chapter…
    chapter_text: str | None = None   # …or a pasted draft
    focus: str = "Rough Draft"
    message: str = ""
    conversation_history: list[dict] = []


@router.post("/review/stream")
def review_stream(req: ReviewRequest):
    s = get_state()
    if req.focus not in FOCUS_PROMPTS:
        raise HTTPException(400, f"unknown focus: {req.focus}")

    # resolve the chapter text
    text = req.chapter_text
    if text is None and req.chapter is not None:
        rows = s.db.execute(
            "SELECT text FROM chunks WHERE book_number = ? AND chapter_number = ? "
            "ORDER BY chunk_index", (req.book, req.chapter)).fetchall()
        if not rows:
            raise HTTPException(404, "chapter not found")
        text = "\n\n".join(r[0] for r in rows)
    if not text:
        raise HTTPException(400, "no chapter selected or pasted")

    def generate():
        # retrieve series context relevant to this chapter (continuity fuel)
        probe = req.message or text[:1500]
        plan = QueryPlan(question=probe, qtype="general",
                         scope=Scope(book_min=1, book_max=req.book))
        excerpts, notes = s.retriever.retrieve(plan)

        question = req.message or f"Give your {req.focus} review of this chapter."
        review_plan = QueryPlan(
            question=(f"CHAPTER UNDER REVIEW (Book {req.book}"
                      + (f", Chapter {req.chapter}" if req.chapter else ", new draft")
                      + f"):\n\n{text}\n\n{question}"),
            qtype="general")

        answerer = s.new_answerer()
        history = [{"role": m["role"], "content": m["content"]}
                   for m in req.conversation_history[-6:]
                   if m.get("role") in ("user", "assistant") and m.get("content")]
        for delta in answerer.answer_stream(review_plan, excerpts, notes,
                                            history=history,
                                            system_extra=FOCUS_PROMPTS[req.focus]):
            yield {"type": "chunk", "content": delta}
        yield citations_payload(excerpts)
        yield {"type": "usage", "model": answerer.model,
               "cost_usd": answerer.actual_cost_usd}

    return stream_response(generate())

"""Review pane: focused AI feedback on a chapter (synced or pasted draft)."""

from __future__ import annotations

import logging
import sqlite3

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


REVIEW_SYSTEM = """You are an experienced developmental editor giving feedback on a fiction manuscript to its author. The chapter marked CHAPTER UNDER REVIEW is the document you are reviewing — all of your feedback must be about that chapter.

The STORY SO FAR notes and manuscript excerpts are background from EARLIER in the series, provided so you can judge continuity and consistency. Do not review, summarize, or give feedback on the background material itself. Use it only to check the chapter against what came before, citing (Book N, Chapter M) when you flag a conflict or confirm a callback. If the background is insufficient to judge a continuity question, say so rather than guessing. Never invent series details that are not present in the provided material."""

STORY_NOTES_HEADER = ("== STORY SO FAR (events from earlier in the series, "
                      "for continuity checking — not under review) ==")

# how many events immediately preceding the chapter get full summaries
_DIGEST_TAIL = 12
# hard cap on digest lines; oldest lines drop first (recency matters most)
_DIGEST_MAX = 120


class ReviewRequest(BaseModel):
    book: int | str
    chapter: int | None = None        # synced chapter…
    chapter_text: str | None = None   # …or a pasted draft
    focus: str = "Rough Draft"
    message: str = ""
    conversation_history: list[dict] = []


def _story_so_far(db, book: int, chapter: int | None) -> list[str]:
    """Chronological digest of enriched events strictly before the reviewed
    chapter: title-only lines for older major events, full summaries for the
    events immediately preceding the chapter. A pasted draft (chapter=None)
    is assumed to follow everything synced for its book."""
    if chapter is None:
        cond, params = "book_number <= ?", [book]
    else:
        cond = "book_number < ? OR (book_number = ? AND chapter_number < ?)"
        params = [book, book, chapter]
    try:
        rows = db.execute(
            f"""SELECT book_number, chapter_number, title, granularity, summary
                FROM events WHERE {cond}
                ORDER BY book_number, chapter_number, position""", params).fetchall()
    except sqlite3.OperationalError:    # enrichment hasn't run yet
        return []
    if not rows:
        return []
    lines = []
    for i, (bn, cn, title, gran, summary) in enumerate(rows):
        if i >= len(rows) - _DIGEST_TAIL:
            lines.append(f"- (Book {bn}, Ch {cn}) {title}: {summary}")
        elif gran == "major":
            lines.append(f"- (Book {bn}, Ch {cn}) {title}")
    if len(lines) > _DIGEST_MAX:
        dropped = len(lines) - _DIGEST_MAX
        lines = [f"(…{dropped} earlier events omitted)"] + lines[-_DIGEST_MAX:]
    return lines


def _probes(text: str, message: str) -> list[str]:
    """Retrieval probes covering the whole chapter, not just its opening."""
    probes = [message] if message.strip() else []
    n = len(text)
    if n <= 1500:
        probes.append(text)
    else:
        mid = n // 2
        probes += [text[:1500], text[mid - 750:mid + 750], text[-1500:]]
    return probes


@router.post("/review/stream")
def review_stream(req: ReviewRequest):
    s = get_state()
    if req.focus not in FOCUS_PROMPTS:
        raise HTTPException(400, f"unknown focus: {req.focus}")
    if isinstance(req.book, str) and not req.book.isdigit():
        titles = {t.lower(): n for n, t in s.db.execute(
            "SELECT DISTINCT book_number, book_title FROM chunks")}
        req.book = titles.get(req.book.lower(), 1)
    else:
        req.book = int(req.book)

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

    # context bound: strictly BEFORE the chapter under review. A prologue
    # (or chapter 0/1) gets earlier books only; a pasted draft is assumed
    # to come after everything synced for its book.
    if req.chapter is not None and req.chapter > 0:
        scope = Scope(book_min=1, book_max=req.book, chapter_max=req.chapter - 1)
    elif req.chapter is not None:                       # prologue / chapter 0
        scope = Scope(book_min=1, book_max=req.book - 1)
    else:                                               # pasted draft
        scope = Scope(book_min=1, book_max=req.book)
    no_prior = scope.book_max is not None and scope.book_max < 1

    def generate():
        # semantic context from before the chapter, probing several slices
        # of the chapter so retrieval isn't skewed to whatever it opens with
        excerpts: list[dict] = []
        if not no_prior:
            seen = set()
            per_probe = max(3, s.cfg.top_k_results // 2)
            for probe in _probes(text, req.message):
                plan = QueryPlan(question=probe, qtype="general", scope=scope)
                for e in s.retriever._semantic(plan, top_k=per_probe):
                    if e["chunk_id"] not in seen:
                        seen.add(e["chunk_id"])
                        excerpts.append(e)
            excerpts = excerpts[:s.cfg.top_k_results + 2]
        notes = [] if no_prior else _story_so_far(s.db, req.book, req.chapter)

        question = req.message or f"Give your {req.focus} review of this chapter."
        review_plan = QueryPlan(
            question=(f"CHAPTER UNDER REVIEW (Book {req.book}"
                      + (f", Chapter {req.chapter}" if req.chapter is not None
                         else ", new draft")
                      + f"):\n\n{text}\n\n{question}"),
            qtype="general")

        answerer = s.new_answerer()
        history = [{"role": m["role"], "content": m["content"]}
                   for m in req.conversation_history[-6:]
                   if m.get("role") in ("user", "assistant") and m.get("content")]
        for delta in answerer.answer_stream(review_plan, excerpts, notes,
                                            history=history,
                                            system_extra=FOCUS_PROMPTS[req.focus],
                                            system_base=REVIEW_SYSTEM,
                                            notes_header=STORY_NOTES_HEADER):
            yield {"type": "chunk", "content": delta}
        yield citations_payload(excerpts)
        yield {"type": "usage", "model": answerer.model,
               "cost_usd": answerer.actual_cost_usd}

    return stream_response(generate())

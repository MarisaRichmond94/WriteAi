"""Review pane: focused AI feedback on a chapter (synced or pasted draft)."""

from __future__ import annotations

import difflib
import logging
import sqlite3
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.costlog import log_cost, usage_diff
from src.query_router import QueryPlan, Scope

from ..deps import get_state
from ..sse import citations_payload, stream_response

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Reviewer personas: each reads the same chapter with different priorities,
# expertise, and voice. The persona rides in system_extra under REVIEW_SYSTEM.
FOCUS_PROMPTS = {
    "Literary Agent": (
        "REVIEWER PERSONA: a seasoned literary agent reading this chapter the "
        "way you read submissions — with a full inbox and honed commercial "
        "instincts. React to the hook, the voice, the tension, and the market: "
        "where you leaned in, the exact line where you would have stopped "
        "reading (if any), and whether you would request more pages. Flag "
        "anything that would make an acquiring editor hesitate. Be candid the "
        "way agents are candid: warm about what sells the story, blunt about "
        "what doesn't."),
    "Casual Reader": (
        "REVIEWER PERSONA: a casual reader who picked this series up for fun. "
        "No craft jargon — just honest gut reactions: where you were hooked, "
        "bored, confused, or moved; which characters you're rooting for or "
        "tired of; whether you'd keep reading past this chapter or set the "
        "book down (and at exactly what moment either way). Talk like you're "
        "telling a friend about it."),
    "Hard-Core Reader": (
        "REVIEWER PERSONA: a devoted superfan who has read every book in this "
        "series multiple times and remembers everything. Read the chapter the "
        "way you'd read a new release at midnight: delight in callbacks and "
        "payoffs, catalog new reveals against your theories, and be ruthless "
        "about anything that contradicts canon — character voice drift, "
        "timeline slips, someone knowing what they can't know yet. Lean hard "
        "on the background material and cite (Book N, Chapter M) for every "
        "catch. End with where you think the story is heading."),
    "Philosopher": (
        "REVIEWER PERSONA: a philosopher reading beneath the plot. What is "
        "this chapter actually about — what moral questions it stages, what "
        "each character's choices reveal about their values, what the imagery "
        "and structure are doing thematically, and how it deepens (or muddies) "
        "the questions the series has been asking. Point to the specific "
        "moments that carry the weight, and name the questions the chapter "
        "raises but doesn't answer."),
    "What-If Explorer": (
        "REVIEWER PERSONA: a story consultant exploring the roads not taken. "
        "Identify the 2-4 pivotal decision points in this chapter — moments "
        "where a character's choice, a reveal's timing, or a scene's direction "
        "could plausibly have gone another way. For each, play out the "
        "strongest alternate path, staying true to the characters as "
        "established in the background material, then weigh what that version "
        "gains and loses against the chapter as written. Finish with a "
        "verdict: which choices are already the strongest version, and which "
        "alternate is worth the author's consideration. If the author asks "
        "about a specific what-if, make that the centerpiece."),
}

# pre-persona focus values (old saved sessions) -> nearest persona
LEGACY_FOCUS = {
    "Rough Draft": "Casual Reader",
    "Continuity": "Hard-Core Reader",
    "Character Voice": "Hard-Core Reader",
    "Line Edit": "Literary Agent",
    "Pacing": "Literary Agent",
}


REVIEW_SYSTEM = """You are giving the author feedback on a chapter of her own manuscript, in the reviewer persona described below. Stay in that persona's perspective, priorities, and voice throughout — but whatever the persona, be concrete and honest: praise that names what works, criticism that names what doesn't and why.

The chapter marked CHAPTER UNDER REVIEW is the document you are reviewing — all of your feedback must be about that chapter. The STORY SO FAR notes and manuscript excerpts are background from EARLIER in the series, provided so you can read the chapter the way someone who knows the series would. Do not review, summarize, or give feedback on the background material itself. Cite (Book N, Chapter M) when a point rests on earlier material. If the background is insufficient to judge something, say so rather than guessing. Never invent series details that are not present in the provided material."""

# Appended when the request asks for it (the UI defaults it ON for the
# first review of a session and OFF for follow-up iterations — the rewrite
# is the dominant output cost).
IDEAL_VERSION_INSTRUCTION = """When the author asks for a review of the chapter (as opposed to a specific follow-up question), end your reply with a section headed "## Ideal Version" — your best revision of the chapter with your recommended changes applied, marked up as tracked changes:
- wrap every addition or rewritten passage in **bold**
- wrap every deletion in ~~strikethrough~~ (a replacement shows the old text struck through, immediately followed by the bolded new text)
- omit unchanged paragraphs; replace any run of consecutive unchanged paragraphs with `...` on its own line (blank line before and after it), so the author sees only what changed.
Include only paragraphs you touched, in their original order. Begin with `...` if the first changed paragraph is not the chapter opener; end with `...` if the last changed paragraph is not the chapter closer.
Preserve paragraphing in the passages you do include: each paragraph on its own line with a BLANK LINE between paragraphs (your reply renders as markdown, which merges single line breaks — without the blank lines the whole chapter congeals into one block). A deleted paragraph stays in place as its own struck-through paragraph; an added one gets its own bolded paragraph.
Reserve bold EXCLUSIVELY for marked additions throughout your reply — never use it for emphasis or headings-in-prose. For follow-up questions, include a revised passage with the same markup only when the author asks for a rewrite."""

NO_IDEAL_INSTRUCTION = """Do not produce a full rewritten version of the chapter. If a passage needs rework, quote the specific lines and show your suggested replacement inline — wrap suggested new text in **bold** and text to delete in ~~strikethrough~~ — but keep it to the passages that matter, not the whole chapter."""

STORY_NOTES_HEADER = ("== STORY SO FAR (events from earlier in the series, "
                      "for continuity checking — not under review) ==")

# Re-review of an updated draft: the previous draft never survives in the
# conversation history (user turns store only the short message), so without
# an explicit diff the model must reconstruct "what changed" from its own
# earlier reply — the main source of hallucinated repetitions/regressions.
DRAFT_DIFF_HEADER = ("== CHANGES FROM THE PREVIOUS DRAFT (computed diff of the "
                     "draft you last reviewed against the chapter above) ==")
DRAFT_DIFF_INSTRUCTION = (
    "The chapter above is the author's updated draft of the SAME chapter you "
    "reviewed earlier in this conversation — it replaces that draft; it is "
    "not a new or repeated chapter. The diff lists every passage that "
    "changed; everything not listed is unchanged from the draft you already "
    "reviewed. Base your assessment of what changed strictly on the diff — "
    "do not infer other changes, and do not treat unchanged prose as new or "
    "repeated material.")

# how many events immediately preceding the chapter get full summaries
_DIGEST_TAIL = 12
# hard cap on digest lines; oldest lines drop first (recency matters most)
_DIGEST_MAX = 120


class ReviewRequest(BaseModel):
    book: int | str
    chapter: int | None = None        # synced chapter…
    chapter_text: str | None = None   # …or a pasted/draft text (wins over the index)
    previous_text: str | None = None  # draft reviewed last turn (re-review diffs against it)
    focus: str = "Casual Reader"
    message: str = ""
    conversation_history: list[dict] = []
    include_ideal: bool = True        # append the tracked-changes rewrite
    model: str | None = None          # per-request model (None = settings default)


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
    # for the reviewed book itself, prose chapter summaries (when enriched)
    # replace per-event lines — tighter and more narrative
    try:
        ch_cond = ("chapter_number < ?" if chapter is not None else "1=1")
        ch_params = [book, chapter] if chapter is not None else [book]
        prose = db.execute(
            f"""SELECT chapter_number, summary FROM chapter_summaries
                WHERE book_number = ? AND {ch_cond}
                ORDER BY chapter_number""", ch_params).fetchall()
    except sqlite3.OperationalError:
        prose = []
    if prose:
        covered = {cn for cn, _ in prose}
        rows = [r for r in rows if not (r[0] == book and r[1] in covered)]
        rows += [(book, cn, None, "summary", text) for cn, text in prose]
        rows.sort(key=lambda r: (r[0], r[1]))
    if not rows:
        return []
    lines = []
    for i, (bn, cn, title, gran, summary) in enumerate(rows):
        ch = "Prologue" if cn == 0 else f"Ch {cn}"
        if gran == "summary":               # prose chapter summary line
            lines.append(f"- (Book {bn}, {ch}) {summary}")
        elif i >= len(rows) - _DIGEST_TAIL:
            lines.append(f"- (Book {bn}, {ch}) {title}: {summary}")
        elif gran == "major":
            lines.append(f"- (Book {bn}, {ch}) {title}")
    if len(lines) > _DIGEST_MAX:
        dropped = len(lines) - _DIGEST_MAX
        lines = [f"(…{dropped} earlier events omitted)"] + lines[-_DIGEST_MAX:]
    return lines


def _draft_diff(old: str, new: str) -> str:
    """Readable paragraph-level diff between two drafts of the same chapter.
    Empty string when nothing changed beyond whitespace."""
    old_paras = [p.strip() for p in old.split("\n\n") if p.strip()]
    new_paras = [p.strip() for p in new.split("\n\n") if p.strip()]
    sm = difflib.SequenceMatcher(a=old_paras, b=new_paras, autojunk=False)
    blocks = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        block = [f"--- change {len(blocks) + 1} ---"]
        if tag in ("replace", "delete"):
            block.append("BEFORE:" if tag == "replace" else "REMOVED:")
            block += old_paras[i1:i2]
        if tag in ("replace", "insert"):
            block.append("AFTER:" if tag == "replace" else "ADDED:")
            block += new_paras[j1:j2]
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


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
    req.focus = LEGACY_FOCUS.get(req.focus, req.focus)
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

        question = req.message or f"Give your review of this chapter as a {req.focus}."
        if req.chapter is None:
            ch_label = ", new draft"
        else:
            ch_label = ", Prologue" if req.chapter == 0 else f", Chapter {req.chapter}"
            meta_row = s.db.execute(
                "SELECT pov_character, date_line FROM chunks "
                "WHERE book_number = ? AND chapter_number = ? "
                "ORDER BY chunk_index LIMIT 1",
                (req.book, req.chapter)).fetchone()
            if meta_row:
                if meta_row[0]:
                    ch_label += f", POV {meta_row[0]}"
                if meta_row[1]:
                    ch_label += f", {meta_row[1]}"
        chapter_block = (f"CHAPTER UNDER REVIEW (Book {req.book}{ch_label}):"
                         f"\n\n{text}")
        if req.previous_text and req.previous_text != text:
            diff = _draft_diff(req.previous_text, text)
            if diff:
                chapter_block += (f"\n\n{DRAFT_DIFF_HEADER}\n{diff}"
                                  f"\n\n{DRAFT_DIFF_INSTRUCTION}")
        review_plan = QueryPlan(
            question=f"{chapter_block}\n\n{question}",
            qtype="general")

        answerer = s.new_answerer(model=req.model)
        history = [{"role": m["role"], "content": m["content"]}
                   for m in req.conversation_history[-6:]
                   if m.get("role") in ("user", "assistant") and m.get("content")]
        # the Ideal Version section rewrites the whole chapter with markup —
        # far past the default 12K output budget
        ideal = IDEAL_VERSION_INSTRUCTION if req.include_ideal else NO_IDEAL_INSTRUCTION
        u0, c0, t0 = dict(answerer.usage), answerer.actual_cost_usd, time.monotonic()
        for delta in answerer.answer_stream(review_plan, excerpts, notes,
                                            history=history,
                                            system_extra=FOCUS_PROMPTS[req.focus],
                                            system_base=f"{REVIEW_SYSTEM}\n\n{ideal}",
                                            notes_header=STORY_NOTES_HEADER,
                                            max_tokens=32000 if req.include_ideal else 12000):
            yield {"type": "chunk", "content": delta}
        log_cost(s.cfg, surface="review", model=answerer.model, qtype="general",
                 usage=usage_diff(answerer.usage, u0),
                 cost_usd=round(answerer.actual_cost_usd - c0, 4),
                 latency_ms=int((time.monotonic() - t0) * 1000),
                 extra={"focus": req.focus, "include_ideal": req.include_ideal,
                        "draft_rereview": bool(req.previous_text)})
        yield citations_payload(excerpts)
        yield {"type": "usage", "model": answerer.model,
               "cost_usd": answerer.actual_cost_usd}

    return stream_response(generate())

"""Review pane: focused AI feedback on a chapter (synced or pasted draft)."""

from __future__ import annotations

import difflib
import logging
import re
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.costlog import cost_scope
from src.query_router import QueryPlan, Scope

from .. import outline_store
from ..deps import get_state
from ..sse import citations_payload, stream_response
from ..digests import book_digest
from .books import _build_bible

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

# personas that review with the author's plan in hand. The reader-simulating
# personas (Casual Reader, Hard-Core Reader) stay blind to what comes next —
# their whole value is reacting as readers who don't know the future.
FORWARD_PERSONAS = {"Literary Agent", "Philosopher", "What-If Explorer"}

# pre-persona focus values (old saved sessions) -> nearest persona
LEGACY_FOCUS = {
    "Rough Draft": "Casual Reader",
    "Continuity": "Hard-Core Reader",
    "Character Voice": "Hard-Core Reader",
    "Line Edit": "Literary Agent",
    "Pacing": "Literary Agent",
}


REVIEW_SYSTEM = """You are giving the author feedback on a chapter of her own manuscript, in the reviewer persona described below. Stay in that persona's perspective, priorities, and voice throughout — but whatever the persona, be concrete and honest: praise that names what works, criticism that names what doesn't and why.

The chapter marked CHAPTER UNDER REVIEW is the document you are reviewing — all of your feedback must be about that chapter. The STORY SO FAR notes, condensed story bibles, and manuscript excerpts are background material, provided so you can read the chapter the way someone who knows the series would. Do not review, summarize, or give feedback on the background material itself. Cite (Book N, Chapter M) when a point rests on earlier material. If the background is insufficient to judge something, say so rather than guessing. Never invent series details that are not present in the provided material."""

# Appended when the request opts in via the UI's Ideal Version toggle —
# the rewrite is the dominant output cost and rarely earns it on a first
# pass, so it is off by default and the targeted suggestions below take
# its place.
IDEAL_VERSION_INSTRUCTION = """When the author asks for a review of the chapter (as opposed to a specific follow-up question), end your reply with a section headed "## Ideal Version" — your best revision of the chapter with your recommended changes applied, marked up as tracked changes:
- wrap every addition or rewritten passage in **bold**
- wrap every deletion in ~~strikethrough~~ (a replacement shows the old text struck through, immediately followed by the bolded new text)
- omit unchanged paragraphs; replace any run of consecutive unchanged paragraphs with `...` on its own line (blank line before and after it), so the author sees only what changed.
Include only paragraphs you touched, in their original order. Begin with `...` if the first changed paragraph is not the chapter opener; end with `...` if the last changed paragraph is not the chapter closer.
Preserve paragraphing in the passages you do include: each paragraph on its own line with a BLANK LINE between paragraphs (your reply renders as markdown, which merges single line breaks — without the blank lines the whole chapter congeals into one block). A deleted paragraph stays in place as its own struck-through paragraph; an added one gets its own bolded paragraph.
Reserve bold EXCLUSIVELY for marked additions throughout your reply — never use it for emphasis or headings-in-prose. For follow-up questions, include a revised passage with the same markup only when the author asks for a rewrite."""

NO_IDEAL_INSTRUCTION = """Do not produce a full rewritten version of the chapter. When the author asks for a review of the chapter (as opposed to a specific follow-up question), end your reply with a section headed "## What To Revise" — the 3-5 changes that would most improve the chapter, in priority order, judged by your persona's priorities. For each: quote the passage (or name the exact moment), say what isn't working and why it matters to a reader like you, and give a concrete fix — where a line-level rewrite helps, show it inline with suggested new text in **bold** and text to delete in ~~strikethrough~~. Keep suggestions to the passages that matter, not the whole chapter; if fewer than three changes are genuinely worth making, list only those rather than inventing work. Reserve bold EXCLUSIVELY for suggested new text throughout your reply — never for emphasis."""

STORY_NOTES_HEADER = ("== STORY SO FAR (events from earlier in the series, "
                      "for continuity checking — not under review) ==")

# rides in system_extra (with the persona) so it lands inside the cached
# system block — follow-up turns in a session read it at the cache rate
BIBLE_PREAMBLE = (
    "Condensed story bibles for the series so far follow: chapter-by-chapter "
    "summaries of recent earlier books (older books may appear as condensed "
    "digests covering their arc, reveals, and outcomes), and the major "
    "characters (traits, arcs, relationships) of the book under review. "
    "Background reference assembled "
    "from the manuscripts — use it to read the chapter the way someone who "
    "knows the series would, not as material to review. Note the character "
    "profiles and arcs summarize each book as a whole, so they may reach past "
    "the chapter under review.")

UPCOMING_HEADER = ("== WHERE THE STORY IS HEADED (the author's plan for what "
                   "follows this chapter — not under review) ==")
UPCOMING_INSTRUCTION = (
    "Use the WHERE THE STORY IS HEADED notes to judge setup, foreshadowing, "
    "and whether this chapter earns its place in the arc — but review the "
    "chapter from the reader's seat: the reader has not seen any of it, and "
    "the chapter cannot be faulted for not yet revealing it.")

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

# conversation window sent to the model. The FIRST exchange (the original
# review) is pinned: re-review turns explicitly refer back to "your earlier
# feedback", which a blind tail window evicts by round three.
_HISTORY_KEEP = 6

# an assistant reply's "## Ideal Version" section is a near-full rewrite of
# the chapter; replayed on later turns it reads as the chapter appearing
# twice and gets misattributed to the author as repetition
_IDEAL_RE = re.compile(r"^#{1,4}\s*Ideal Version\b.*$",
                       re.MULTILINE | re.IGNORECASE)

# background excerpts whose word-shingles mostly appear in the chapter under
# review are almost certainly a stale indexed copy of that very chapter
# (e.g. at its pre-renumbering position) — the numeric scope can't catch those
_SELF_SIM = 0.5


class ReviewRequest(BaseModel):
    book: int | str
    chapter: int | None = None        # synced chapter…
    chapter_text: str | None = None   # …or a pasted/draft text (wins over the index)
    previous_text: str | None = None  # draft reviewed last turn (re-review diffs against it)
    focus: str = "Casual Reader"
    message: str = ""
    conversation_history: list[dict] = []
    include_ideal: bool = False       # opt in to the tracked-changes rewrite
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
    # the EXISTS guards skip enrichment rows stranded at chapter numbers that
    # no longer exist in the index (renumbered/removed chapters): they repeat
    # the story under stale labels until an enrichment run GCs them
    try:
        rows = db.execute(
            f"""SELECT book_number, chapter_number, title, granularity, summary
                FROM events WHERE ({cond})
                  AND EXISTS (SELECT 1 FROM chunks k
                              WHERE k.book_number = events.book_number
                                AND k.chapter_number = events.chapter_number)
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
                  AND EXISTS (SELECT 1 FROM chunks k
                              WHERE k.book_number = chapter_summaries.book_number
                                AND k.chapter_number = chapter_summaries.chapter_number)
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
    # each chapter's date header, so the digest doubles as a series timeline
    dates = {(bn, cn): dl for bn, cn, dl in db.execute(
        """SELECT book_number, chapter_number, MIN(date_line) FROM chunks
           WHERE date_line IS NOT NULL
           GROUP BY book_number, chapter_number""")}
    lines = []
    for i, (bn, cn, title, gran, summary) in enumerate(rows):
        ch = "Prologue" if cn == 0 else f"Ch {cn}"
        when = dates.get((bn, cn))
        loc = f"Book {bn}, {ch}" + (f" — {when}" if when else "")
        if gran == "summary":               # prose chapter summary line
            lines.append(f"- ({loc}) {summary}")
        elif i >= len(rows) - _DIGEST_TAIL:
            lines.append(f"- ({loc}) {title}: {summary}")
        elif gran == "major":
            lines.append(f"- ({loc}) {title}")
    if len(lines) > _DIGEST_MAX:
        dropped = len(lines) - _DIGEST_MAX
        lines = [f"(…{dropped} earlier events omitted)"] + lines[-_DIGEST_MAX:]
    return lines


def _tag_free(html_str: str) -> str:
    """Writer outline summaries are stored as TipTap HTML — flatten to text."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_str)).strip()


def _upcoming(s, book: int, chapter: int | None) -> list[str]:
    """One line per chapter after the reviewed one, in story order: enriched
    prose summaries for written chapters, the writer's Plan-pane outline
    cards (writer_summary, else extracted bullets) for the rest — including
    planned-but-unwritten chapters. A pasted draft (chapter=None) is assumed
    to follow everything synced for its book."""
    if chapter is None:
        row = s.db.execute("SELECT MAX(chapter_number) FROM chunks "
                           "WHERE book_number = ?", (book,)).fetchone()
        chapter = row[0] if row and row[0] is not None else 0
    written: dict[int, str] = {}
    try:
        written = dict(s.db.execute(
            """SELECT chapter_number, summary FROM chapter_summaries
               WHERE book_number = ? AND chapter_number > ?
                 AND EXISTS (SELECT 1 FROM chunks k
                             WHERE k.book_number = chapter_summaries.book_number
                               AND k.chapter_number = chapter_summaries.chapter_number)
               ORDER BY chapter_number""", (book, chapter)))
    except sqlite3.OperationalError:    # enrichment hasn't run yet
        pass
    try:
        cards = outline_store.chapters_for(book)
    except Exception:                   # outline store unreadable — skip it
        log.warning("review: could not read the plan outline", exc_info=True)
        cards = []
    entries: list[tuple[float, str]] = []
    for cn, summ in written.items():
        entries.append((float(cn), f"- (Ch {cn} — written) {summ}"))
    for card in cards:
        cn = card.get("chapter")
        pos = card.get("position")
        pos = float(pos if pos is not None else (cn if cn is not None else 0))
        # skip cards at or before the reviewed chapter, and written chapters
        # already covered by their enriched summary
        if cn in written or pos <= float(chapter) \
                or (cn is not None and cn <= chapter):
            continue
        summ = (_tag_free(card.get("writer_summary") or "")
                or "; ".join(card.get("extracted_bullets") or []))
        if not summ:
            continue
        head = card.get("heading") or (f"Ch {cn}" if cn is not None
                                       else "Planned chapter")
        status = "written" if cn is not None else "planned"
        entries.append((pos, f"- ({head} — {status}) {summ}"))
    return [line for _, line in sorted(entries, key=lambda t: t[0])]


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


def _strip_ideal(content: str) -> str:
    """Drop the tracked-changes rewrite from a replayed assistant reply,
    keeping the critique above it. The rewrite is a near-copy of the chapter
    — on later turns the model sees it next to the re-sent draft and
    misreads the duplication as the author repeating herself."""
    m = _IDEAL_RE.search(content)
    if m is None:
        return content
    return (content[:m.start()].rstrip()
            + "\n\n[A full tracked-changes rewrite of the chapter followed "
              "here — omitted from the replayed conversation.]")


def _condense_history(raw: list[dict]) -> list[dict]:
    """API-ready conversation history: Ideal Version rewrites stripped, the
    first exchange pinned, the most recent turns kept."""
    msgs = [{"role": m["role"],
             "content": (_strip_ideal(m["content"]) if m["role"] == "assistant"
                         else m["content"])}
            for m in raw
            if m.get("role") in ("user", "assistant") and m.get("content")]
    if len(msgs) <= _HISTORY_KEEP:
        return msgs
    if msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant":
        head, rest = msgs[:2], msgs[2:]
    else:                               # unexpected shape — plain tail window
        head, rest = [], msgs
    tail = rest[-(_HISTORY_KEEP - len(head)):]
    while tail and tail[0]["role"] != "user":   # keep roles alternating
        tail.pop(0)
    return head + tail


def _shingles(text: str, n: int = 8) -> set[tuple[str, ...]]:
    """Overlapping n-word windows — cheap, order-sensitive text fingerprint."""
    words = text.lower().split()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def _match_indexed_chapter(db, book: int, text: str) -> int | None:
    """The chapter of `book` a pasted draft is a revision of, if any.

    A paste with no chapter number is otherwise scoped as following the whole
    book — wrong when it is really a rework of an indexed chapter: the old
    copy of that same chapter becomes retrievable background and the story
    digest includes the chapter itself. A majority of the draft's shingles
    landing in one chapter is decisive; a mostly-new chapter matches nothing
    and keeps the end-of-book scoping."""
    draft = _shingles(text)
    if not draft:
        return None
    chapters: dict[int, list[str]] = {}
    for cn, t in db.execute(
            "SELECT chapter_number, text FROM chunks WHERE book_number = ? "
            "ORDER BY chapter_number, chunk_index", (book,)):
        chapters.setdefault(cn, []).append(t)
    best, best_ratio = None, 0.0
    for cn, parts in chapters.items():
        ratio = len(draft & _shingles("\n\n".join(parts))) / len(draft)
        if ratio > best_ratio:
            best, best_ratio = cn, ratio
    return best if best_ratio >= _SELF_SIM else None


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
        # within a chunk paragraphs are stored "\n"-joined; re-expand so the
        # model sees every paragraph break as a consistent blank line (the
        # Ideal Version instructions depend on real paragraphing)
        text = "\n\n".join(p for r in rows
                           for p in r[0].split("\n") if p.strip())
    if not text:
        raise HTTPException(400, "no chapter selected or pasted")

    # a pasted draft is often a revision of an already-indexed chapter —
    # recognize it and scope as that chapter, so its old copy doesn't come
    # back as "earlier" background
    if req.chapter is None:
        req.chapter = _match_indexed_chapter(s.db, req.book, text)
        if req.chapter is not None:
            log.info("review: pasted draft matched Book %s Chapter %s — "
                     "scoping as a revision of it", req.book, req.chapter)

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
        degraded: str | None = None     # set when the review runs on less context
        if not no_prior:
            seen = set()
            dropped_self = 0
            chapter_shingles = _shingles(text)
            per_probe = max(3, s.cfg.top_k_results // 2)
            try:
                for probe in _probes(text, req.message):
                    plan = QueryPlan(question=probe, qtype="general", scope=scope)
                    for e in s.retriever._semantic(plan, top_k=per_probe):
                        if e["chunk_id"] in seen:
                            continue
                        seen.add(e["chunk_id"])
                        # a stale copy of the chapter under review (say, indexed
                        # at its pre-renumbering number) passes the numeric scope
                        # but reads as the author repeating the chapter — drop on
                        # content overlap
                        esh = _shingles(e["text"])
                        if esh and len(esh & chapter_shingles) / len(esh) >= _SELF_SIM:
                            dropped_self += 1
                            continue
                        excerpts.append(e)
            except Exception:
                # Never let retrieval kill the stream. A re-index in another
                # process can leave this process's cached Chroma handle
                # inconsistent with the rewritten segments; degrade to a review
                # with no prior-context excerpts (the story-so-far notes below
                # still come from SQLite) rather than emit a blank bubble.
                # The store reopens and retries once before it gets here, so
                # reaching this point means retrieval is genuinely unavailable.
                log.exception("review: semantic retrieval failed — continuing "
                              "without prior-context excerpts")
                excerpts = []
                degraded = ("Prior-context search was unavailable, so this "
                            "review read the chapter with the story bibles and "
                            "story-so-far notes but no retrieved manuscript "
                            "excerpts. Re-syncing the book usually clears it.")
            if dropped_self:
                log.info("review: dropped %d excerpt(s) near-identical to the "
                         "chapter under review", dropped_self)
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

        # condensed story bibles (chapter summaries for the earlier books,
        # character profiles for the reviewed book) ride in system_extra with
        # the persona: deterministic, zero LLM cost to build, and inside the
        # cached system block so follow-up turns read them at the cache rate
        extra_parts = [FOCUS_PROMPTS[req.focus]]
        bible_parts = []
        for bn in range(1, req.book + 1):
            try:
                # Books two or more behind the reviewed one ride as stored
                # condensed digests (~1.5K tokens each vs ~12K for a full
                # chapter-by-chapter bible). The previous book keeps full
                # detail — its callbacks are the ones a new chapter leans on.
                if bn <= req.book - 2:
                    digest = book_digest(s, bn)
                    if digest:
                        bible_parts.append(digest)
                        continue
                _, md = _build_bible(s, bn, compact=True,
                                     characters=(bn == req.book),
                                     chapters=(bn < req.book))
                bible_parts.append(md)
            except Exception:
                log.warning("review: could not build bible for book %s", bn)
        if bible_parts:
            extra_parts.append(BIBLE_PREAMBLE + "\n\n"
                               + "\n\n---\n\n".join(bible_parts))
        # forward context for the author-side personas only — the reader
        # personas review without knowing what comes next
        if req.focus in FORWARD_PERSONAS:
            upcoming = _upcoming(s, req.book, req.chapter)
            if upcoming:
                extra_parts.append(UPCOMING_HEADER + "\n" + "\n".join(upcoming)
                                   + "\n\n" + UPCOMING_INSTRUCTION)

        answerer = s.new_answerer(model=req.model)
        history = _condense_history(req.conversation_history)
        # the Ideal Version section rewrites the whole chapter with markup —
        # far past the default 12K output budget
        ideal = IDEAL_VERSION_INSTRUCTION if req.include_ideal else NO_IDEAL_INSTRUCTION
        # ahead of the reply, so the writer knows the review is running on
        # thinner context while she reads it — not after she has acted on it
        if degraded:
            yield {"type": "notice", "message": degraded}
        # the scope ledgers the request from a `finally`, so a review that dies
        # mid-stream still shows up in the spend dashboard (marked failed)
        # instead of vanishing from it
        with cost_scope(s.cfg, surface="review", answerer=answerer,
                        qtype="general",
                        extra={"focus": req.focus,
                               "include_ideal": req.include_ideal,
                               "draft_rereview": bool(req.previous_text)}):
            for delta in answerer.answer_stream(review_plan, excerpts, notes,
                                                history=history,
                                                system_extra="\n\n".join(extra_parts),
                                                system_base=f"{REVIEW_SYSTEM}\n\n{ideal}",
                                                notes_header=STORY_NOTES_HEADER,
                                                max_tokens=32000 if req.include_ideal else 12000):
                yield {"type": "chunk", "content": delta}
        yield citations_payload(excerpts)
        yield {"type": "usage", "model": answerer.model,
               "cost_usd": answerer.actual_cost_usd}

    return stream_response(generate())

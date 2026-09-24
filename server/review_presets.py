"""Versioned review-experience presets.

The literary-agent review's quality is set by a bundle of knobs — system
prompt, quote rules, excerpt budgets, story-so-far gisting, digest policy,
forward-block policy, reasoning effort — that were tuned piecemeal through
September 2026 (first for cost, then patching the failures the cost pass
caused). A preset freezes one coherent bundle so configurations can be
compared side by side at request time, without rebuilds or restarts.

Selection: ReviewRequest.preset > REVIEW_PRESET env > "current". Every
review ledgers its preset name (cost.jsonl extra), so quality impressions
stay attributable to the exact configuration that produced them.

Presets:
- current       — the code's present-day defaults (the constants in
                  server/routers/review.py remain the single source of
                  truth; this preset just points at them).
- aug31         — faithful reconstruction of the end-of-August experience,
                  before the 2026-09-01 cost pass (git aa532af^): short
                  2-paragraph system prompt, Explore's verbatim quote rules,
                  full excerpt budget for every persona, ungisted story-so-
                  far, ALL earlier books as condensed digests (the previous-
                  book full bible arrived later), soft forward-block rules
                  with the Literary Agent forward-looking, no first-
                  appearance gate, uncapped thinking.
- aug31-guarded — August's context richness and reasoning depth plus the
                  September guardrails that fixed real incidents (chronology
                  hard rules, reader-knowledge and granularity rules, first-
                  appearance gate, Literary Agent blind to the plan, capped
                  forward block, previous-book full bible). The arm to beat.

Cache note: switching presets rewrites the stable cached system block
(one-time cost per switch); an unchanged preset caches exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .routers import review as _r


@dataclass(frozen=True)
class ReviewPreset:
    name: str
    description: str
    system_base: str
    # None -> the answerer's default verbatim QUOTE_INSTRUCTION ("" omits)
    quote_instruction: str | None
    bible_preamble: str
    upcoming_header: str
    upcoming_instruction: str
    forward_personas: frozenset[str]
    upcoming_window: int | None          # None = uncapped
    upcoming_gist: bool
    # persona -> excerpt budget; personas absent here get the full top_k+2
    excerpt_budgets: dict[str, int] = field(default_factory=dict)
    gist_story_notes: bool = True
    # how many most-recent EARLIER books keep their full chapter-by-chapter
    # bible (older ones ride as condensed digests): 1 = previous book full
    digest_keep_full_books: int = 1
    first_appearance_gate: bool = True
    # "cfg" = follow cfg.review_effort; "none" = uncapped (API default);
    # else an explicit effort level
    effort: str = "cfg"


# ---------------------------------------------------------------------------
# aug31 — texts reproduced verbatim from git aa532af^ (2026-08-31 state)
# ---------------------------------------------------------------------------

_AUG31_SYSTEM = """You are giving the author feedback on a chapter of her own manuscript, in the reviewer persona described below. Stay in that persona's perspective, priorities, and voice throughout — but whatever the persona, be concrete and honest: praise that names what works, criticism that names what doesn't and why.

The chapter marked CHAPTER UNDER REVIEW is the document you are reviewing — all of your feedback must be about that chapter. The STORY SO FAR notes, condensed story bibles, and manuscript excerpts are background material, provided so you can read the chapter the way someone who knows the series would. Do not review, summarize, or give feedback on the background material itself. Cite (Book N, Chapter M) when a point rests on earlier material. If the background is insufficient to judge something, say so rather than guessing. Never invent series details that are not present in the provided material."""

_AUG31_BIBLE_PREAMBLE = (
    "Condensed story bibles for the series so far follow: earlier books as "
    "condensed digests covering their arc, reveals, and outcomes (a book "
    "may appear as chapter-by-chapter summaries where no digest exists), "
    "and the major characters of this chapter (traits, arcs, relationships) "
    "for the book under review. "
    "Background reference assembled "
    "from the manuscripts — use it to read the chapter the way someone who "
    "knows the series would, not as material to review. Note the character "
    "profiles and arcs summarize each book as a whole, so they may reach past "
    "the chapter under review.")

_AUG31_UPCOMING_HEADER = (
    "== WHERE THE STORY IS HEADED (the author's plan for what "
    "follows this chapter — not under review) ==")

_AUG31_UPCOMING_INSTRUCTION = (
    "Use the WHERE THE STORY IS HEADED notes to judge setup, foreshadowing, "
    "and whether this chapter earns its place in the arc — but review the "
    "chapter from the reader's seat: the reader has not seen any of it, and "
    "the chapter cannot be faulted for not yet revealing it.")


def _current() -> ReviewPreset:
    return ReviewPreset(
        name="current",
        description="Today's defaults: September guardrails, gisted notes, "
                    "per-persona excerpt budgets, capped forward block, "
                    "REVIEW_EFFORT from the environment.",
        system_base=_r.REVIEW_SYSTEM,
        quote_instruction=_r.REVIEW_QUOTE_INSTRUCTION,
        bible_preamble=_r.BIBLE_PREAMBLE,
        upcoming_header=_r.UPCOMING_HEADER,
        upcoming_instruction=_r.UPCOMING_INSTRUCTION,
        forward_personas=frozenset(_r.FORWARD_PERSONAS),
        upcoming_window=_r._UPCOMING_WINDOW,
        upcoming_gist=True,
        excerpt_budgets={"Casual Reader": _r._EXCERPT_LIGHT,
                         "Philosopher": _r._EXCERPT_LIGHT,
                         "Literary Agent": _r._EXCERPT_AGENT},
        gist_story_notes=True,
        digest_keep_full_books=1,
        first_appearance_gate=True,
        effort="cfg",
    )


def _aug31() -> ReviewPreset:
    return ReviewPreset(
        name="aug31",
        description="End-of-August baseline (pre cost pass): short prompt, "
                    "verbatim quotes, full excerpts for every persona, "
                    "ungisted notes, all earlier books as digests, soft "
                    "forward rules with the Literary Agent forward-looking, "
                    "no first-appearance gate, uncapped thinking.",
        system_base=_AUG31_SYSTEM,
        quote_instruction=None,          # Explore's verbatim quote rules
        bible_preamble=_AUG31_BIBLE_PREAMBLE,
        upcoming_header=_AUG31_UPCOMING_HEADER,
        upcoming_instruction=_AUG31_UPCOMING_INSTRUCTION,
        forward_personas=frozenset({"Literary Agent", "Philosopher",
                                    "What-If Explorer"}),
        upcoming_window=None,
        upcoming_gist=False,
        excerpt_budgets={},              # full top_k+2 for everyone
        gist_story_notes=False,
        digest_keep_full_books=0,        # every earlier book condensed
        first_appearance_gate=False,
        effort="none",                   # API default (uncapped thinking)
    )


def _aug31_guarded() -> ReviewPreset:
    return ReviewPreset(
        name="aug31-guarded",
        description="August context richness and reasoning depth + the "
                    "September guardrails: full excerpts, ungisted notes, "
                    "uncapped thinking, previous book full, chronology/"
                    "granularity rules, Literary Agent blind to the plan.",
        system_base=_r.REVIEW_SYSTEM,
        quote_instruction=_r.REVIEW_QUOTE_INSTRUCTION,
        bible_preamble=_r.BIBLE_PREAMBLE,
        upcoming_header=_r.UPCOMING_HEADER,
        upcoming_instruction=_r.UPCOMING_INSTRUCTION,
        forward_personas=frozenset(_r.FORWARD_PERSONAS),
        upcoming_window=_r._UPCOMING_WINDOW,
        upcoming_gist=True,
        excerpt_budgets={},              # full top_k+2 for everyone
        gist_story_notes=False,
        digest_keep_full_books=1,
        first_appearance_gate=True,
        effort="none",                   # uncapped thinking
    )


def presets() -> dict[str, ReviewPreset]:
    """Built fresh per call so the current preset always reflects the live
    constants in review.py (they are the source of truth, not a copy)."""
    return {p.name: p for p in (_current(), _aug31(), _aug31_guarded())}


def resolve_preset(requested: str | None, cfg_default: str) -> ReviewPreset:
    """Request choice > REVIEW_PRESET env > current. Unknown names fall back
    to current rather than failing the review."""
    reg = presets()
    for name in (requested, cfg_default, "current"):
        if name and name in reg:
            return reg[name]
    return reg["current"]


EFFORT_CHOICES = ("low", "medium", "high", "xhigh", "max", "none")


def resolve_effort(req_effort: str | None, preset: ReviewPreset,
                   cfg_effort: str) -> str | None:
    """Effective effort cap for answer_stream: an explicit request choice
    wins, then the preset, with "cfg" following the REVIEW_EFFORT env var.
    Returns None for uncapped (the API's adaptive default)."""
    level = req_effort or preset.effort
    if level == "cfg":
        level = cfg_effort
    return None if level in ("", "none", None) else level

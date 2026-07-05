#!/usr/bin/env python3
"""Diagnose Anthropic prompt-cache behavior across WriteAi's query surfaces.

Read-only: never touches the database or manuscripts; makes no API calls in
the default --dry-run mode (count_tokens is a free endpoint). Findings are
written up in eval/CACHE_NOTES.md.

Modes
-----
--dry-run (default, FREE)
    Uses /v1/messages/count_tokens to measure the system-block size of each
    surface (cli-query, chat-without-bible, chat-with-bible) against the
    model's minimum cacheable prefix, and checks that the story-bible
    renderer is byte-stable across calls. Prints a verdict per surface.

--live (2 paid calls, max_tokens=64 — a few cents)
    Sends the chat-with-bible request twice and prints
    cache_creation/cache_read tokens for both calls.
      write -> read   healthy: the prefix cached on call 1, was reused on 2
      zero  -> zero   prefix below the model's minimum cacheable size
      write -> write  byte instability: the prefix differs between calls

--live --flag-on
    Same, but with ENABLE_PROMPT_CACHE_V2 behavior and a fake 2-turn chat
    history, demonstrating the turn-N+1 prefix reuse the flag buys.

Usage:
    python scripts/check_cache.py                # free
    python scripts/check_cache.py --live         # flag-off live probe
    python scripts/check_cache.py --live --flag-on
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from config import load_config  # noqa: E402
from src.answerer import SYSTEM_PROMPT, Answerer  # noqa: E402
from src.query_router import QueryPlan  # noqa: E402

# Minimum cacheable prefix per model family (prefixes shorter than this
# silently never cache — no error, just cache_creation_input_tokens: 0).
MIN_CACHEABLE = (
    ("opus-4", 4096),
    ("haiku-4-5", 4096),
    ("sonnet-4-6", 2048),
    ("fable-5", 2048),
    ("sonnet-4-5", 1024),
)


def min_cacheable(model: str) -> tuple[int, bool]:
    """(minimum, known). Unknown models fall back to the most conservative."""
    for fragment, n in MIN_CACHEABLE:
        if fragment in model:
            return n, True
    return 4096, False


# ── representative request material (deterministic) ─────────────────────────

SAMPLE_QUESTION = "How does Wren's understanding of the bond evolve in Book 2?"

SAMPLE_NOTES = [
    "- Wren first senses the bond in Book 2, Chapter 4 (foreshadowed B1 Ch22).",
    "- The bond's cost is revealed by Maera in Book 2, Chapter 11.",
    "- Open question: whether the bond can be severed without killing the host.",
]

SAMPLE_EXCERPTS = [
    {"header": f"Book 2, Chapter {ch} — {pov} POV",
     "text": ("The corridor smelled of cold iron and old rain. " * 12).strip()}
    for ch, pov in ((4, "Wren"), (7, "Kade"), (11, "Wren"), (15, "Maera"))
]

FAKE_HISTORY = [
    {"role": "user",
     "content": "Give me an overview of the major arcs across the series."},
    {"role": "assistant",
     "content": ("Across the series, three arcs dominate. First, Wren's "
                 "arc moves from denial of the bond to mastery of it, with "
                 "the turning point in Book 2, Chapter 11 when Maera names "
                 "its cost. Second, the political arc: the Council's slow "
                 "unraveling, seeded in Book 1 and paid off in Book 4. "
                 "Third, the Kade/Wren relationship, which shifts from "
                 "wary alliance to partnership over Books 2-3. " * 4)},
]

BIBLE_PREAMBLE = (
    "The following condensed story bibles cover the books the author has in "
    "scope — major characters plus a chapter-by-chapter summary of each "
    "book. Use them for overarching, cross-book questions; the retrieved "
    "excerpts remain the source of truth for verbatim detail.\n\n"
)


def synthetic_bible() -> str:
    """A stand-in of realistic size (~3K tokens) when the real DB-backed
    bible isn't buildable in this environment."""
    md = ["# Story Bible — Book 2: The Hollow Crown (synthetic stand-in)", ""]
    md.append("## Characters\n")
    for i in range(10):
        md.append(f"### Character {i + 1}")
        md.append("- **Traits:** wary, loyal, sharp-tongued, superstitious")
        md.append("- **Arc in this book:** moves from suspicion of the court "
                  "to reluctant service, tested by the events at the ford.")
        md.append("- **Relationships:** Character A (rival), Character B "
                  "(mentor), Character C (estranged kin)")
        md.append("")
    md.append("## Chapters\n")
    for ch in range(1, 31):
        md.append(f"### Chapter {ch}")
        md.append("A confrontation at the river ford forces a choice between "
                  "the oath sworn in the previous book and the new alliance; "
                  "the chapter ends with a message arriving under a false "
                  "seal, which the POV character misreads as a summons. " * 2)
        md.append("")
    return "\n".join(md)


def real_bible():
    """Try to render the real compact bible twice; returns
    (markdown, byte_stable, source) or None if not buildable here."""
    try:
        from server.deps import get_state
        from server.routers.books import _build_bible
        s = get_state()
        row = s.db.execute("SELECT MIN(book_number) FROM chunks").fetchone()
        if not row or row[0] is None:
            return None
        book = row[0]
        _, md1 = _build_bible(s, book, compact=True)
        _, md2 = _build_bible(s, book, compact=True)
        return md1, md1 == md2, f"_build_bible(book={book}, compact=True)"
    except Exception as e:  # missing DB, no server deps, etc.
        print(f"  (real bible not buildable here: {type(e).__name__}: {e})")
        return None


# ── request assembly ─────────────────────────────────────────────────────────

def make_answerer(cfg, flag_on: bool) -> Answerer:
    a = Answerer(cfg)
    a.enable_prompt_cache_v2 = flag_on
    return a


def chat_request(answerer: Answerer, bible_md: str | None,
                 history: list[dict] | None, nonce: str) -> dict:
    plan = QueryPlan(question=SAMPLE_QUESTION, qtype="general")
    extra = (BIBLE_PREAMBLE + bible_md) if bible_md else ""
    if nonce:  # keeps live runs independent of earlier runs' cache entries
        extra = (extra + "\n\n" if extra else "") + nonce
    return answerer.build_request(plan, SAMPLE_EXCERPTS, SAMPLE_NOTES,
                                  history=history, system_extra=extra)


# ── dry run ──────────────────────────────────────────────────────────────────

def count_tokens(client, model: str, *, system: str | None = None,
                 messages: list[dict] | None = None) -> int:
    kwargs = {"model": model,
              "messages": messages or [{"role": "user", "content": "hi"}]}
    if system is not None:
        kwargs["system"] = system
    return client.messages.count_tokens(**kwargs).input_tokens


def dry_run(cfg) -> int:
    answerer = make_answerer(cfg, flag_on=False)
    client, model = answerer.client, answerer.model
    minimum, known = min_cacheable(model)
    print(f"model: {model}   minimum cacheable prefix: {minimum} tokens"
          + ("" if known else " (unknown model — conservative assumption)"))
    print()

    print("story-bible byte-stability check:")
    rb = real_bible()
    if rb:
        bible_md, stable, source = rb
        print(f"  source: {source}")
        print(f"  rendered twice -> {'IDENTICAL' if stable else 'DIFFERS'}"
              f" ({len(bible_md):,} chars)")
        if not stable:
            print("  WARNING: unstable bible bytes invalidate the cache on "
                  "every turn — fix determinism before enabling the flag.")
    else:
        bible_md = synthetic_bible()
        print(f"  using synthetic stand-in ({len(bible_md):,} chars)")
    print()

    baseline = count_tokens(client, model)  # the trivial message alone
    surfaces = [
        ("cli-query", SYSTEM_PROMPT,
         "one-shot; excerpts/notes are in the user message AFTER the "
         "breakpoint"),
        ("chat-without-bible", SYSTEM_PROMPT,
         "no filters selected -> no bible injected"),
        ("chat-with-bible", SYSTEM_PROMPT + "\n\n" + BIBLE_PREAMBLE + bible_md,
         "book filter selected -> compact bible in system_extra"),
    ]
    print(f"{'surface':<20} {'system tokens':>14} {'minimum':>8}  verdict")
    print("-" * 78)
    worst = 0
    for name, system_text, note in surfaces:
        n = count_tokens(client, model, system=system_text) - baseline
        cacheable = n >= minimum
        verdict = "CACHEABLE" if cacheable else "NEVER CACHES (below minimum)"
        print(f"{name:<20} {n:>14,} {minimum:>8}  {verdict}")
        print(f"{'':<20} {note}")
        if not cacheable:
            worst += 1
    print()
    print("notes:")
    print("  - The cache breakpoint sits on the system block only; retrieved")
    print("    excerpts/notes live in the user message and are never part of")
    print("    the cached prefix regardless of size.")
    print("  - ENABLE_PROMPT_CACHE_V2 adds a second breakpoint on the last")
    print("    prior chat turn so multi-turn sessions also reuse history.")
    return 0


# ── live probe ───────────────────────────────────────────────────────────────

def live_run(cfg, flag_on: bool) -> int:
    answerer = make_answerer(cfg, flag_on)
    rb = real_bible()
    bible_md = rb[0] if rb else synthetic_bible()
    nonce = ("[cache-diagnostic run "
             f"{datetime.now(timezone.utc).isoformat()}]")
    history = FAKE_HISTORY if flag_on else None
    request = chat_request(answerer, bible_md, history, nonce)
    request["max_tokens"] = 64

    n_marks = sum(1 for m in request["messages"]
                  for b in (m["content"] if isinstance(m["content"], list)
                            else [])
                  if isinstance(b, dict) and "cache_control" in b)
    print(f"live probe  flag={'ON' if flag_on else 'OFF'}  "
          f"model={answerer.model}  history_turns={len(history or [])}  "
          f"message-breakpoints={n_marks} (+1 on system)")

    stats = []
    for i in (1, 2):
        r = answerer.client.messages.create(**request)
        u = r.usage
        write = getattr(u, "cache_creation_input_tokens", 0) or 0
        read = getattr(u, "cache_read_input_tokens", 0) or 0
        stats.append((write, read))
        print(f"  call {i}: input={u.input_tokens:,}  cache_write={write:,}  "
              f"cache_read={read:,}  output={u.output_tokens}")
        answerer._record_usage(u)
        if i == 1:
            time.sleep(1)  # cache entry becomes readable once call 1 streams

    (w1, r1), (w2, r2) = stats
    if w1 > 0 and r2 > 0 and w2 == 0:
        print("  verdict: HEALTHY — call 1 wrote the prefix, call 2 read it")
    elif w1 == 0 and w2 == 0 and r1 == 0 and r2 == 0:
        print("  verdict: NO CACHING — prefix below the model minimum")
    elif w1 > 0 and w2 > 0:
        print("  verdict: BYTE INSTABILITY — both calls wrote; the prefix "
              "differs between requests")
    else:
        print("  verdict: MIXED — see numbers above (a partial read can mean "
              "an earlier run's entry was reused)")
    print(f"  probe cost: ${answerer.actual_cost_usd}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true",
                   help="free token-count diagnosis (default)")
    p.add_argument("--live", action="store_true",
                   help="send 2 small paid requests and report cache usage")
    p.add_argument("--flag-on", action="store_true",
                   help="with --live: probe ENABLE_PROMPT_CACHE_V2 behavior "
                        "with a fake 2-turn history")
    args = p.parse_args()

    cfg = load_config()
    if args.live:
        return live_run(cfg, flag_on=args.flag_on)
    return dry_run(cfg)


if __name__ == "__main__":
    sys.exit(main())

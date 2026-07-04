# Prompt-Cache Notes (WP9)

Diagnosis of why the Anthropic prompt-cache marker in `src/answerer.py`
`build_request` never engages on the query path, what the bible-injecting
chat path does, and what the flag-gated fix (`ENABLE_PROMPT_CACHE_V2`)
changes. All numbers below were measured with `scripts/check_cache.py`
against `claude-sonnet-4-6` on 2026-07-04.

## TL;DR

| Surface | Cacheable prefix | Minimum | Result |
|---|---:|---:|---|
| CLI query (`query.py`) | 80 tokens | 2,048 | **never caches** — inherent, not fixable |
| Chat, no book filter | 80 tokens | 2,048 | never caches |
| Chat, book filter → bible injected | 6,267 tokens | 2,048 | caches today (system block) |
| Chat turn N+1 history | — | — | **not cached today**; covered by `ENABLE_PROMPT_CACHE_V2` |

## The empirical zero-cache evidence

The 40-question answers baseline
(`eval/results/20260704-083619_baseline-answers.json`, label
`baseline-answers`, $3.75) shows across all 40 items:

```
total_usage: input_tokens=1,070,359  output_tokens=35,934
             cache_write_tokens=0    cache_read_tokens=0
```

Every one of the 41 usage records (40 per-item + total) has both cache
counters at exactly 0 — the `cache_control: {"type": "ephemeral"}` marker
on the system block never engaged once.

## Root cause: the prefix is 80 tokens; the minimum is 2,048

`claude-sonnet-4-6` silently refuses to cache any prefix shorter than
2,048 tokens (no error — just `cache_creation_input_tokens: 0`).
`check_cache.py --dry-run` (free, via the `count_tokens` endpoint):

```
model: claude-sonnet-4-6   minimum cacheable prefix: 2048 tokens

surface               system tokens  minimum  verdict
cli-query                        80     2048  NEVER CACHES (below minimum)
chat-without-bible               80     2048  NEVER CACHES (below minimum)
chat-with-bible               6,267     2048  CACHEABLE
```

The base `SYSTEM_PROMPT` is ~80 tokens. The bulky stable content — story
notes and retrieved excerpts (the eval averaged ~26K input tokens per
question) — sits in the **user message**, *after* the breakpoint, so it can
never be part of the cached prefix regardless of size. And because every
CLI query retrieves different excerpts, those bytes differ per request
anyway: **one-shot CLI queries are inherently uncacheable.** Documented,
not fixed — padding the system prompt to 2,048 tokens would change the
model's input for pennies of theoretical savings and is explicitly out of
scope.

## The bible path: byte-stable and already caching

Explore chat with a book filter injects a compact story bible via
`server/routers/books.py::_build_bible` into `system_extra`, pushing the
system block to ~6.3K tokens — over the minimum. Byte-stability check
(rendered twice, diffed): **IDENTICAL** (26,318 chars for book 1,
compact). The renderer is deterministic — SQL with explicit `ORDER BY`,
`sorted()` on every set, insertion-ordered dicts — so repeated turns
produce the same bytes and the cache key holds.

Live proof, flag OFF (`check_cache.py --live`, 2 calls at `max_tokens=64`):

```
call 1: input=727  cache_write=6,295  cache_read=0
call 2: input=727  cache_write=0      cache_read=6,295
verdict: HEALTHY — call 1 wrote the prefix, call 2 read it
```

So bible-backed chat sessions already cache the **system block**. What
they do *not* cache is the conversation history: on turn N+1 the prior
turns sit between the system breakpoint and the new user message with no
breakpoint of their own, and are re-processed at full input price every
turn.

## What `ENABLE_PROMPT_CACHE_V2` changes

Env flag → `Config.enable_prompt_cache_v2` (default **false**; documented
in `.env.example`). When on and `build_request` receives a non-empty
`history`, the last content block of the last history message also gets
`cache_control: {"type": "ephemeral"}` (string content is converted to the
equivalent single-text-block form to carry the marker — same bytes on the
wire). Total breakpoints: 2 (system + history tail), under the API max
of 4.

Effect: on turn N+1 of a chat session the entire prefix — system prompt +
bible + all prior turns — is one cache read instead of a full-price
re-process. Live proof, flag ON with a fake 2-turn history:

```
call 1: input=727  cache_write=6,743  cache_read=0
call 2: input=727  cache_write=0      cache_read=6,743
verdict: HEALTHY
```

The 448-token history span moved from the (would-be) full-price region
into the cached prefix. No prompt **text** changes under the flag — only
cache metadata — and with the flag off the request payload is byte-for-byte
identical to the pre-change code (asserted against the pre-change
`build_request` for representative inputs, with and without history).

## Expected savings math

Sonnet 4.6 input reprices at **0.1×** for cache reads, **1.25×** for
5-minute-TTL cache writes. For a chat session whose stable prefix
(system + bible + accumulated history) is *P* tokens at turn *k*:

- Turn 1: pay 1.25×*P* (write premium) — a 25% surcharge, once.
- Turns ≥ 2 (within the 5-min TTL): pay 0.1×*P* instead of 1.0×*P* —
  a **90% discount** on the prefix.
- Break-even after the second turn: 1.25 + 0.1 = 1.35× vs 2× uncached.

Concretely, a 5-turn session over a 6.3K-token bible system block plus
~450 tokens of growing history per turn: uncached prefix cost ≈
5 × 7K × $3/MTok ≈ 10.5¢; with the flag ≈ (1.25 × 7K + 4 × 0.1 × 7K) ×
$3/MTok ≈ 3.5¢ — roughly **65–70% off the prefix** portion, growing with
session length. (The per-turn retrieved excerpts remain full price by
design — they differ every turn.)

Caveat: turns must arrive within the 5-minute TTL for the read to hit;
a slow-moving conversation re-pays the write premium each time the entry
expires. That is why the flag defaults off pending real-session data.

## Observability

- `logs/cost.jsonl` (WP10) already records `cache_write_tokens` /
  `cache_read_tokens` per request.
- The chat SSE `usage` event now also carries `cache_write_tokens` /
  `cache_read_tokens` (previously they were folded into `input_tokens`
  with no breakdown).
- `scripts/check_cache.py` re-runs this whole diagnosis: `--dry-run` is
  free; `--live [--flag-on]` costs a few cents.

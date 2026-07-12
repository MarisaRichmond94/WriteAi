# RAG Optimization Handoff — WriteAi (Dark Horse Series)

**Date:** 2026-07-11, session paused ~11:59 PM PT. Prepared for continuation by another Claude session (Opus).
**Commit:** `<HASH>` on `master` — code + this file committed together; working tree and this doc agree.

**Task:** Raise judged answer correctness from 0.484 toward ≥0.70 on `eval/golden_textgrounded.jsonl` (92 items, "training set") without touching chunking, embeddings, or extraction (Haiku-locked). Continuity was ruled **diagnostic-only** by the user mid-session (its "this chapter" questions have no identifiable referent; several are structurally unanswerable — do not optimize for it or gate on it). Verdicts use the four core qtypes — temporal_knowledge, sentiment, lookup, general — and every kept change must improve-or-hold on BOTH the training set and the held-out set (`eval/golden_holdout.jsonl`, 79 items, never tuned against).

---

## 1. Final config (reproduce from this section alone)

**Env flags (the eval harness reads these per-run; they are NOT in `.env` — see Open decisions):**

```bash
export RERANKER_MODEL=BAAI/bge-reranker-v2-m3   # was cross-encoder/ms-marco-MiniLM-L-6-v2
export RERANK_CANDIDATES=200                    # was 80
export CONTINUITY_NOTES_CAP=200                 # was 0 (which made note-ranking inert)
# SENTIMENT_RERANK_DOCS: leave UNSET (defaults to "beats"). "prose" was tried and REVERTED.
# MULTI_QUERY / HYBRID_QTYPES: leave UNSET pending the in-flight arm results (section 5).
```

All other flags stay as in `.env` (all ENABLE_* already true, TOP_K_RESULTS=15, EXTRACTION_MODEL=claude-haiku-4-5, QUERY_MODEL=claude-sonnet-4-6).

**Code changes (committed in `<HASH>`):**

- `src/retriever.py`
  - `_lookup()` → new `_mention_scan()`: "…where X is *mentioned*" enumerations are answered by a literal word-bounded text scan (≤24 chunks), matched chunks returned as the excerpts plus one "this list is exhaustive" note; falls back to the legacy tag-notes path when nothing matches or footprint exceeds cap.
  - `_ranked_continuity_notes()`: bi-encoder shortlist (cap×2) is now cross-encoder-reranked and emitted **most-relevant-first** under a header saying so (reranker off → legacy chronological).
  - `_continuity()`: ranked-notes branch retrieves full `top_k` excerpts (was hardcoded 5).
  - `_sentiment_v2_excerpts()`: scoring-doc shape switchable via `SENTIMENT_RERANK_DOCS` env (beats | beats+quotes | prose); default `beats` = legacy behavior.
  - `_semantic()`: two env-gated experiment arms — `MULTI_QUERY=strip` (RRF-union with a boilerplate-stripped query variant via `_strip_question_boilerplate()`) and `HYBRID_QTYPES` (comma list extending BM25 fusion beyond lookup/temporal). Both inert when unset.
- `src/query_router.py`: for lookup qtype, a lone "book N" mention sets `book_min = book_max` (enumerations are locative), instead of only an upper bound (temporal semantics).
- `src/answerer.py`: `CONTINUITY_INSTRUCTION` — direct answer first; report format only for audit-style questions; anchor to the single excerpt the question describes. `TEMPORAL_INSTRUCTION` — answer only the asked aspect, don't dump unrelated ledger knowledge.

**One-command training eval with the final config:**
```bash
cd ~/Documents/GitHub/WriteAi && RERANKER_MODEL=BAAI/bge-reranker-v2-m3 RERANK_CANDIDATES=200 \
CONTINUITY_NOTES_CAP=200 .venv/bin/python eval/run_eval.py \
  --set eval/golden_textgrounded.jsonl --label repro
```

---

## 2. Final scoreboard (baseline → final config)

**Judged answer correctness (Opus judge — the official metric):**

| qtype | training | held-out |
|---|---|---|
| lookup | 0.575 → **1.000** | **NOT RUN** |
| general | 0.500 → 0.684 | NOT RUN |
| temporal_knowledge | 0.475 → 0.675 | NOT RUN |
| sentiment | 0.475 → 0.650 *(stale — see note)* | NOT RUN |
| **four-category mean** | **0.506 → 0.753** *(stale for sentiment)* | **NOT RUN — THE DECISIVE NUMBER** |
| continuity (diagnostic only) | 0.346 → 0.308 (n=13, noise) | NOT RUN |
| overall (all items) | 0.484 → 0.690 | NOT RUN |

> **Decisive number still missing:** held-out judged correctness was NOT run (session paused before spending it; ~$5–6). Command in section 7. Interpretation per user: held-out four-cat mean near training's ~0.75 (≥~0.72) ⇒ gains generalize; a large gap ⇒ walk back levers that don't replicate.
> **Stale note:** training sentiment 0.650 was judged under `SENTIMENT_RERANK_DOCS=prose`, since reverted. Re-judge sentiment-only with final config (~$1, section 7) and splice; expect somewhat lower.

**Retrieval hit@k (free gating metric):**

| qtype | training | held-out |
|---|---|---|
| general | 0.474 → 0.737 | 0.562 → **0.875** |
| lookup (recall@k) | 0.619 → **1.000** | 0.709 → **1.000** |
| temporal_knowledge | 0.650 → 0.800 | 0.562 → 0.625 |
| sentiment | 0.300 → 0.450 | 0.500 → 0.562 |
| continuity (diagnostic) | 0.077 → 0.308 | 0.267 → 0.333 |
| overall | 0.522 → 0.728 | 0.582 → 0.671 |

No category regressed on either set. (Sentiment rows are the final beats-docs config.)

**Why retrieval gains translate to judged gains:** baseline per-item correlation — mean judge score on retrieval hits: general 0.94, sentiment 0.93, temporal 0.69; on misses: 0.07–0.23.

---

## 3. Kept levers (each survived train + held-out)

1. **Lookup mention-scan + locative scope (code).** Mechanism: "where is X mentioned" has exact ground truth (name in prose); the old path fed alias-expanded tag notes claiming mentions in chapters where the name never appears (judge: fabrication) plus semantic samples (recall 0.62). Train: recall 0.62→1.00, judged 0.575→1.000. Held-out: recall 0.71→1.00.
2. **Reranker upgrade + breadth (env): bge-reranker-v2-m3 @ 200 candidates.** Mechanism: every candidate is "about Jared"; only a strong cross-encoder discriminates the asked fact, and the 80-cap was cutting gold chunks before rerank (diagnostic: 9/14 sentiment misses in-pool-but-ranked-out, 5/14 cut by cap). Train hit@k: general .474→.737, temporal .650→.800, sentiment .300→.450. Held-out: general .562→.875, temporal .562→.625, sentiment .500→.562. (bge-reranker-base tried first: marginal, rejected.)
3. **Continuity ranked notes, cap 200, relevance-first (env+code).** Prompts 191k→~10k tokens; right-chapter note present for 12/13 (citation 0.923); cap swept 40/80/120/200/300 → 200. Diagnostic-only category; judged 0.346→0.308 is sample noise on n=13.
4. **Answer instructions (code).** Temporal: judge was half-crediting answers padded with unrelated ledger facts → "answer only the asked aspect". Continuity: direct-answer-first instead of forced audit-report format.

## 4. Reverted levers (overfit signatures)

- **`SENTIMENT_RERANK_DOCS=prose`** — train sentiment hit@k 0.45→0.70 (+5 items) but held-out 0.562→**0.500** (down). Large training gain + held-out decline = the canonical overfit signature; reverted to `beats`. (`beats+quotes` also tried on training: 0.60, in-between; not pursued.)

## 5. Unfinished / in-flight (do not silently drop)

- **HELD-OUT JUDGED RUN — the decisive verdict. Not run.** Command in section 7, ~$5–6.
- **Training sentiment re-judge** under final (beats) config — 0.650 in the table is stale. ~$1.
- **Arm: `HYBRID_QTYPES=…,general` — REJECTED** (decided 23:01). BM25 fusion for general made its target WORSE on training: general hit@k 0.737 → 0.684 (`20260711-224329_tr-hybrid-gen.json`). Fails condition (a); no held-out run needed. Do not revisit without a new mechanism.
- **Arm: `MULTI_QUERY=strip` — RESULT PENDING, runs unattended overnight.** Relaunched detached (pid 13003) under the FINAL config at ~23:05; finishes ~1:00 AM. Result: `eval/results/*_tr-mq-strip.json` (log: `logs/tr-mq-strip.log`). Full 92-item training run — compare per-qtype vs `20260711-071739_locked-config.json` (note: that run used prose sentiment docs; sentiment comparison baseline is hit@k 0.450 beats-mode, from the cap-sweep runs). Decide by the rule below; if it helps, validate on held-out before keeping. Targets: 4 residual general/temporal misses whose gold chunk is absent from the bi-encoder top-200.
- **Arm decision rule (user-mandated):** keep only if it (a) helps its target on training, (b) holds on held-out, (c) regresses none of the other three categories on either set. Free-metric gating only; judged verdict comes from the held-out judge run.
- **HyDE / LLM query rewriting — untested.** Next mechanism if the deterministic arms fail; adds an LLM call per query (latency + cost + nondeterminism); needs a design decision first.
- **User's stop rule:** stop when 2–3 consecutive levers each yield <~1 point on held-out; then report the ceiling.

## 6. Open decisions needing human judgment

1. **Production adoption:** the winning env flags live only in eval commands. Writing them to `.env` makes the interactive app pay v2-m3 rerank latency (CPU: tens of seconds/query; MPS: a few seconds). Options: adopt wholesale, adopt with a smaller RERANK_CANDIDATES, or keep MiniLM interactively and v2-m3 for exports/eval.
2. **Continuity:** accept as eval-instrument artifact (recommended; questions lack a chapter referent) or invest in fixing the eval items themselves.
3. **Budget:** approve the ~$6–7 total for held-out judge + sentiment re-judge.

## 7. Reproduce / verify commands

```bash
cd ~/Documents/GitHub/WriteAi
ENV='RERANKER_MODEL=BAAI/bge-reranker-v2-m3 RERANK_CANDIDATES=200 CONTINUITY_NOTES_CAP=200'

# training eval, free retrieval metrics
env $ENV .venv/bin/python eval/run_eval.py --set eval/golden_textgrounded.jsonl --label verify-train

# held-out eval, free
env $ENV .venv/bin/python eval/run_eval.py --set eval/golden_holdout.jsonl --label verify-holdout

# THE decisive run: held-out answers + judge (~$5-6)
env $ENV .venv/bin/python eval/run_eval.py --set eval/golden_holdout.jsonl --label ho-final --answers
.venv/bin/python eval/judge_answers.py eval/results/<timestamp>_ho-final.json \
  --set eval/golden_holdout.jsonl \
  --db data/backups/20260711-001023_pre-ingest/series_metadata.sqlite \
  --out eval/results/ho-final-judged.json

# training sentiment re-judge under final config (~$1), then splice with final-answers-judged.json
env $ENV .venv/bin/python eval/run_eval.py --set eval/golden_textgrounded.jsonl \
  --only-qtype sentiment --answers --label tr-sent-beats
```

Notes: eval pins `EMBEDDING_DEVICE=cpu` itself (determinism). Judge model is claude-opus-4-8. The `--db` snapshot is the haiku-extraction sqlite (live DB was re-ingested post-baseline; `chunk_hashes.json` identical, golden chunk ids valid). Baseline numbers came from a pristine worktree at pre-change HEAD: `…scratchpad/writeai-baseline` (remove later with `git worktree remove`).

## 8. Result files (eval/results/)

| file | what |
|---|---|
| `haiku-tg-judged.json` | BASELINE training judged (0.484 overall) |
| `20260710-202409_fable-baseline.json` | baseline training retrieval on live DB |
| `20260711-071739_locked-config.json` / `final-answers-judged.json` | final-config training retrieval / judged (0.690; sentiment stale, prose mode) |
| `20260711-154812_holdout-baseline.json` | baseline held-out retrieval (in the scratchpad worktree's `eval/results/`) |
| `20260711-201755_holdout-locked.json` | final-config held-out retrieval |
| `20260711-213159_ho-sent-beats.json` | held-out sentiment, beats vs prose decision run |
| `20260711-131708_cont-topk15.json`, `*cont-rr60/rr200*` | continuity note-rerank sweeps (diagnostic) |
| `20260711-224329_tr-hybrid-gen.json` | hybrid-general arm — REJECTED (general 0.737→0.684) |
| `*_tr-mq-strip.json` (lands ~1:00 AM) | multi-query arm, detached overnight run — see section 5 |

## 9. Spend

~$6.50 so far: training answers $5.26 (Sonnet) + Opus judge runs + a killed partial continuity run.

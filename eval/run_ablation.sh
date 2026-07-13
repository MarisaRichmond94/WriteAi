#!/usr/bin/env bash
# Query-time flag ablation on a 24-item stratified held-out subset
# (eval/ablation_subset.jsonl, 6 each of temporal/sentiment/lookup/general).
#
# Only flags the retriever/answerer read AT QUERY TIME are ablatable here (no
# re-ingest). Excluded by inspection: PROMPT_CACHE_V2 (perf-only),
# STORY_ORDER + LOCATION_V2 (baked at enrichment time). NOTE_RANKING skipped
# (touches ingest). Baseline metrics come from the existing full ho-rebaseline
# run (per-item hit_at_k / judge_score for these 24 ids) — no baseline re-run.
#
# Retrieval-affecting flags -> retrieval-only eval (free, hit@k).
# Answer-shaping flags       -> judged eval (Opus, ~$1-2/arm).
# Runs AFTER the training re-baseline finishes (never two evals at once).

set -uo pipefail
cd "$(dirname "$0")/.."
export EMBEDDING_DEVICE=cpu                       # MPS is unusable for this reranker
PY=.venv/bin/python
SET=eval/ablation_subset.jsonl
mkdir -p eval/results
LOG="eval/results/ablation-$(date +%Y%m%d-%H%M%S).log"
log(){ echo "$@" | tee -a "$LOG"; }

log "=== ablation START $(date) ==="
log "waiting for the training re-baseline (+ its judge) to finish before running..."
while pgrep -f "run_overnight_rebaseline.sh" >/dev/null 2>&1 \
   || pgrep -f "tr-rebaseline" >/dev/null 2>&1; do
  sleep 60
done
log "training done. proceeding $(date)"

retr_arm(){ # FLAG  name — idempotent: skip if a result already exists (resume-safe)
  if ls eval/results/*_abl-"$2"-off.json >/dev/null 2>&1; then
    log "--- [retrieval-only] $2 : already done, skipping ---"; return
  fi
  log ""; log "--- [retrieval-only] $2 : ENABLE_$1=false  $(date) ---"
  env "ENABLE_$1=false" $PY eval/run_eval.py --set "$SET" --label "abl-$2-off" 2>&1 | tee -a "$LOG"
}
judged_arm(){ # FLAG  name — idempotent: skip if the judged result already exists
  if [ -f "eval/results/abl-$2-off-judged.json" ]; then
    log "--- [judged] $2 : already done, skipping ---"; return
  fi
  log ""; log "--- [judged] $2 : ENABLE_$1=false  $(date) ---"
  env "ENABLE_$1=false" $PY eval/run_eval.py --answers --set "$SET" --label "abl-$2-off" 2>&1 | tee -a "$LOG"
  local res; res=$(ls -t eval/results/*_abl-"$2"-off.json 2>/dev/null | head -1)
  if [ -n "$res" ]; then
    $PY eval/judge_answers.py "$res" --set "$SET" --out "eval/results/abl-$2-off-judged.json" 2>&1 | tee -a "$LOG"
  else
    log "!! no result file for $2 — skipping judge"
  fi
}

# free retrieval arms first (partial results land as each completes)
retr_arm HYBRID_SEARCH     hybrid
retr_arm RERANKER          reranker
retr_arm ALIAS_RESOLUTION  alias
# paid judged arms
judged_arm DIRECT_QUOTES    directquotes
judged_arm FIRST_OCCURRENCE firstocc
judged_arm SENTIMENT_V2     sentiment

log ""
log "=== ablation DONE $(date) ==="
log "retrieval arms -> eval/results/*_abl-{hybrid,reranker,alias}-off.json"
log "judged arms    -> eval/results/abl-{directquotes,firstocc,sentiment}-off-judged.json"

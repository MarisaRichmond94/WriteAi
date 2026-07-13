#!/usr/bin/env bash
# Overnight re-baseline on the settled corpus (post 2026-07-12 WAL fix + 8-chunk settle).
#
# Confirms whether the shipped 0.75 held-out judged answer-correctness still holds
# after the Book-3 resync + settle. Runs on CPU on purpose: bge-reranker-v2-m3 is
# pathologically slow on MPS here (~14 min/item, memory thrash) vs ~3 min/item on CPU.
#
# Phases (sequential, ~4-4.5h each):
#   1. HELD-OUT  (79 items) -> the decisive generalization number   [must-have]
#   2. TRAINING  (89 items) -> the secondary train-vs-holdout check  [nice-to-have]
# If you only have one night, phase 1 is the one that matters.
#
# Usage (leave it running unattended):
#   nohup bash eval/run_overnight_rebaseline.sh > /dev/null 2>&1 &
# Then in the morning read the *-judged.json files + the overnight-*.log.

set -uo pipefail
cd "$(dirname "$0")/.."                      # repo root
export EMBEDDING_DEVICE=cpu                  # force CPU; MPS thrashes on this reranker
PY=.venv/bin/python
mkdir -p eval/results
LOG="eval/results/overnight-$(date +%Y%m%d-%H%M%S).log"

log() { echo "$@" | tee -a "$LOG"; }
log "=== overnight re-baseline START $(date) (corpus=1424 chunks, WAL) ==="

run_and_judge () {
  local set_path="$1" label="$2"
  log ""
  log "--- [$label] run_eval --answers  ($set_path)  $(date) ---"
  $PY eval/run_eval.py --answers --set "$set_path" --label "$label" 2>&1 | tee -a "$LOG"
  local res
  res=$(ls -t eval/results/*_"$label".json 2>/dev/null | head -1)
  if [ -z "$res" ]; then log "!! no result file produced for $label — skipping judge"; return 1; fi
  log "--- [$label] judge (Opus)  result=$res  $(date) ---"
  # judge --db defaults to the live settled DB, which the golden sets are grounded against
  $PY eval/judge_answers.py "$res" --set "$set_path" \
      --out "eval/results/${label}-judged.json" 2>&1 | tee -a "$LOG"
}

# Phase 0: self-heal the golden sets against whatever the corpus looks like now
# (the 10:15pm sync may have shifted chunks after they were last grounded).
log ""
log "--- [phase 0] re-validate golden sets against live corpus  $(date) ---"
$PY eval/revalidate_golden.py eval/golden_holdout.jsonl eval/golden_textgrounded.jsonl 2>&1 | tee -a "$LOG"

run_and_judge eval/golden_holdout.jsonl      ho-rebaseline    # 1. decisive (held-out)
run_and_judge eval/golden_textgrounded.jsonl tr-rebaseline    # 2. secondary (training)

log ""
log "=== DONE $(date) ==="
log "Compare four-core means vs shipped: held-out 0.750 / training 0.721"
log "Judged results:"
ls -1 eval/results/*-rebaseline-judged.json 2>/dev/null | tee -a "$LOG"

#!/usr/bin/env bash
# rerank_candidates A/B: does cutting the reranked pool 200 -> 60 hold answer
# quality? Both arms on the 24-item stratified held-out subset, judged (Opus),
# on the identical current corpus so the only variable is the candidate count.
#
# CPU-pinned on purpose: keeps the eval off the GPU (which the live server's
# reranker uses) and off the flaky MPS path. Each arm is explicitly forced via
# RERANK_CANDIDATES on the command line, which overrides the .env value.

set -uo pipefail
cd "$(dirname "$0")/.."
export EMBEDDING_DEVICE=cpu
PY=.venv/bin/python
SET=eval/ablation_subset.jsonl
mkdir -p eval/results
LOG="eval/results/rerank-ab-$(date +%Y%m%d-%H%M%S).log"
log(){ echo "$@" | tee -a "$LOG"; }

log "=== rerank_candidates A/B START $(date) ==="
# never run two evals / an ingest at once (HF model-load contention hangs)
while pgrep -f "ingest.py|run_eval.py|run_ablation.sh" >/dev/null 2>&1; do
  log "waiting for an active ingest/eval to finish..."; sleep 60
done

arm(){ # candidate_count
  local c="$1"
  log ""; log "--- arm rerank_candidates=$c  $(date) ---"
  env RERANK_CANDIDATES="$c" $PY eval/run_eval.py --answers --set "$SET" --label "ab-rerank-$c" 2>&1 | tee -a "$LOG"
  local res; res=$(ls -t eval/results/*_ab-rerank-"$c".json 2>/dev/null | head -1)
  if [ -n "$res" ]; then
    $PY eval/judge_answers.py "$res" --set "$SET" --out "eval/results/ab-rerank-$c-judged.json" 2>&1 | tee -a "$LOG"
  else
    log "!! no result file for arm $c"
  fi
}

arm 200      # current repo default (quality-verified reference)
arm 60       # proposed interactive value (currently live in .env)

log ""
log "=== VERDICT $(date) ==="
$PY - <<'PY' 2>&1 | tee -a "$LOG"
import json, os
core = ["temporal_knowledge", "sentiment", "lookup", "general"]
def summarize(c):
    f = f"eval/results/ab-rerank-{c}-judged.json"
    if not os.path.exists(f):
        return None
    d = json.load(open(f)); pq = d["judge_per_qtype"]
    vals = [(pq[q]["mean"] if isinstance(pq[q], dict) else pq[q]) for q in core if q in pq]
    hit = d["aggregates"]["overall"]["hit_at_k"] if "aggregates" in d else None
    return sum(vals) / len(vals), d.get("judge_overall"), hit
a200, a60 = summarize(200), summarize(60)
if a200 and a60:
    print(f"  rerank=200: four-core={a200[0]:.3f}  overall={a200[1]}  hit@k={a200[2]}")
    print(f"  rerank= 60: four-core={a60[0]:.3f}  overall={a60[1]}  hit@k={a60[2]}")
    d = a60[0] - a200[0]
    print(f"  four-core delta (60 - 200) = {d:+.3f}")
    print("  -> 60 HOLDS, promote to default" if d >= -0.02
          else "  -> 60 REGRESSES, keep 200 (or try a middle value)")
else:
    print("  one or both arms missing; see log above")
PY
log "=== rerank_candidates A/B DONE $(date) ==="

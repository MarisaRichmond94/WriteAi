#!/usr/bin/env bash
# Evaluate faster reranker models as a replacement for bge-reranker-v2-m3
# (which is ~2 min/query on CPU). Two parts:
#   1. SPEED micro-benchmark  — rerank 200 real candidate pairs on CPU, time it.
#   2. QUALITY A/B            — held-out 24-item subset, judged, vs the v2-m3 baseline.
#
# Candidates: ms-marco-MiniLM-L-6-v2 (~22M, fastest) and bge-reranker-base
# (~278M, middle). CPU-pinned. Fully detached / self-logging.

set -uo pipefail
cd "$(dirname "$0")/.."
export EMBEDDING_DEVICE=cpu
PY=.venv/bin/python
SET=eval/ablation_subset.jsonl
mkdir -p eval/results
LOG="eval/results/reranker-models-$(date +%Y%m%d-%H%M%S).log"
log(){ echo "$@" | tee -a "$LOG"; }

log "=== reranker-model test START $(date) ==="

# ---- 1. SPEED: time reranking 200 real (query, chunk) pairs on CPU ----
log ""
log "--- SPEED: rerank 200 candidate pairs on CPU (load once, then time predict) ---"
$PY - <<'PY' 2>&1 | grep -viE "httpx|HTTP Request|resolve-cache|huggingface|Warning|Loading weights|transformers" | tee -a "$LOG"
import os, time, sqlite3
os.environ["EMBEDDING_DEVICE"] = "cpu"
from sentence_transformers import CrossEncoder
rows = sqlite3.connect("data/series_metadata.sqlite").execute(
    "SELECT text FROM chunks LIMIT 200").fetchall()
q = "What does Jared know about the flash drive?"
pairs = [(q, r[0]) for r in rows]
for model in ["BAAI/bge-reranker-v2-m3",
              "cross-encoder/ms-marco-MiniLM-L-6-v2",
              "BAAI/bge-reranker-base"]:
    try:
        t0 = time.time(); m = CrossEncoder(model, device="cpu"); load = time.time() - t0
        t1 = time.time(); m.predict(pairs, show_progress_bar=False); rer = time.time() - t1
        print(f"  {model:42s}  load={load:5.1f}s  rerank_200={rer:7.2f}s")
        del m
    except Exception as e:
        print(f"  {model:42s}  FAILED: {e}")
PY

# ---- 2. QUALITY: held-out subset, judged, per candidate model ----
quality_arm(){ # model  label
  log ""; log "--- QUALITY [$2]  RERANKER_MODEL=$1  $(date) ---"
  env RERANKER_MODEL="$1" $PY eval/run_eval.py --answers --set "$SET" --label "rr-$2" 2>&1 \
    | grep -viE "httpx|HTTP Request|resolve-cache|huggingface|Warning" | tee -a "$LOG"
  local res; res=$(ls -t eval/results/*_rr-"$2".json 2>/dev/null | head -1)
  if [ -n "$res" ]; then
    $PY eval/judge_answers.py "$res" --set "$SET" --out "eval/results/rr-$2-judged.json" 2>&1 \
      | grep -viE "httpx|HTTP Request" | tee -a "$LOG"
  else
    log "!! no result file for $2"
  fi
}
quality_arm "cross-encoder/ms-marco-MiniLM-L-6-v2" minilm
quality_arm "BAAI/bge-reranker-base"               bgebase

# ---- 3. VERDICT ----
log ""; log "=== VERDICT $(date) ==="
$PY - <<'PY' 2>&1 | tee -a "$LOG"
import json, os
core = ["temporal_knowledge", "sentiment", "lookup", "general"]
def fourcore(f):
    if not os.path.exists(f): return None
    d = json.load(open(f)); pq = d["judge_per_qtype"]
    vals = [(pq[q]["mean"] if isinstance(pq[q], dict) else pq[q]) for q in core if q in pq]
    return sum(vals) / len(vals)
base = fourcore("eval/results/ab-rerank-200-judged.json")  # bge-reranker-v2-m3 @200, same subset
base_txt = f"{base:.3f}" if base is not None else "0.729 (prior run; file missing)"
print(f"  bge-reranker-v2-m3 (CURRENT, ~2min/query): four-core = {base_txt}")
ref = base if base is not None else 0.729
for lbl, name in [("minilm", "ms-marco-MiniLM-L-6-v2"), ("bgebase", "bge-reranker-base")]:
    v = fourcore(f"eval/results/rr-{lbl}-judged.json")
    if v is not None:
        print(f"  {name:26s}: four-core = {v:.3f}   delta = {v-ref:+.3f}")
    else:
        print(f"  {name:26s}: (no result)")
print("  (see SPEED section above for the latency win)")
PY
log "=== reranker-model test DONE $(date) ==="

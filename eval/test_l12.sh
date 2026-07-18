#!/usr/bin/env bash
# Middle-option reranker test: ms-marco-MiniLM-L-12-v2 (bigger than L-6, still
# far smaller than bge-reranker-v2-m3). Speed micro-benchmark + FULL 79-item
# held-out judged quality, directly comparable to v2-m3 (0.742) and L-6 (0.696).
set -uo pipefail
cd "$(dirname "$0")/.."
export EMBEDDING_DEVICE=cpu
PY=.venv/bin/python
M="cross-encoder/ms-marco-MiniLM-L-12-v2"
LOG="eval/results/l12-test-$(date +%Y%m%d-%H%M%S).log"
log(){ echo "$@" | tee -a "$LOG"; }

log "=== MiniLM-L-12 test START $(date) ==="
log "--- SPEED: rerank 200 candidate pairs on CPU ---"
$PY - <<'PY' 2>&1 | grep -viE "httpx|HTTP Request|resolve-cache|huggingface|Warning|Loading weights|transformers" | tee -a "$LOG"
import time, sqlite3
from sentence_transformers import CrossEncoder
rows = sqlite3.connect("data/series_metadata.sqlite").execute(
    "SELECT text FROM chunks LIMIT 200").fetchall()
pairs = [("What does Jared know about the flash drive?", r[0]) for r in rows]
t0 = time.time(); m = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-12-v2", device="cpu"); load = time.time()-t0
t1 = time.time(); m.predict(pairs, show_progress_bar=False)
print(f"  ms-marco-MiniLM-L-12-v2  load={load:.1f}s  rerank_200={time.time()-t1:.2f}s")
PY

log ""
log "--- QUALITY: full 79-item held-out, judged  $(date) ---"
env RERANKER_MODEL="$M" $PY eval/run_eval.py --answers --set eval/golden_holdout.jsonl --label rr-l12-full 2>&1 \
  | grep -viE "httpx|HTTP Request|resolve-cache|huggingface|Warning" | tee -a "$LOG"
res=$(ls -t eval/results/*_rr-l12-full.json 2>/dev/null | head -1)
if [ -n "$res" ]; then
  $PY eval/judge_answers.py "$res" --set eval/golden_holdout.jsonl \
    --out eval/results/rr-l12-full-judged.json 2>&1 | grep -viE "httpx|HTTP Request" | tee -a "$LOG"
fi

log ""
log "=== VERDICT $(date) ==="
$PY - <<'PY' 2>&1 | tee -a "$LOG"
import json, os
core = ["temporal_knowledge", "sentiment", "lookup", "general"]
def fc(f):
    if not os.path.exists(f): return None
    d = json.load(open(f)); pq = d["judge_per_qtype"]
    return sum((pq[q]["mean"] if isinstance(pq[q], dict) else pq[q]) for q in core if q in pq)/len(core)
l12 = fc("eval/results/rr-l12-full-judged.json")
print("  bge-reranker-v2-m3 (current): four-core 0.742   rerank_200 ~170s")
print("  MiniLM-L-6:                   four-core 0.696   rerank_200 ~5.4s")
print(f"  MiniLM-L-12:                  four-core {l12:.3f}   rerank_200 (see SPEED above)" if l12 is not None
      else "  MiniLM-L-12:                  (no result)")
PY
log "=== DONE $(date) ==="
echo DONE > /tmp/l12.done

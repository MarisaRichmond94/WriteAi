"""LLM-as-judge answer-correctness scoring for a run_eval.py --answers result.

run_eval.py --answers generates a RAG answer per golden item and stores it on
each per_item row (row["answer"]), alongside retrieval metrics and quote
precision. This script grades those answers for FACTUAL CORRECTNESS with an
independent judge (Opus 4.8), against the source passages and the golden
reference answer — a model-neutral signal the built-in keyword-mention metric
can't give.

The judge sees: the question, the source passage text (the golden item's
expected chunks — the ground-truth support), the reference answer (authored
from that text), and the candidate answer from the pipeline. It is told to
grade only factual correctness + grounding, never style, and to treat a
confidently-wrong or unsupported answer as incorrect.

Usage (repo root):
    .venv/bin/python eval/judge_answers.py eval/results/<label>.json \
        --set eval/golden_textgrounded.jsonl --db <snapshot.sqlite>
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import load_config

JUDGE_MODEL = "claude-opus-4-8"
SCORE = {"correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0}

SYSTEM = """You grade a candidate answer from a retrieval system against ground \
truth. You are given a question, the SOURCE PASSAGES that contain the answer, a \
REFERENCE answer written from those passages, and a CANDIDATE answer to grade.

Grade ONLY factual correctness and grounding in the source — never style, \
length, or phrasing. Rules:
  - "correct": the candidate states the key facts of the reference answer and \
contradicts nothing in the source.
  - "partially_correct": some key facts right but missing a material part, or \
mixing a correct fact with an unsupported/incorrect one.
  - "incorrect": the central claim is wrong, unsupported by the source, or the \
answer fails to actually answer the question (e.g. "I don't know", or retrieves \
the wrong scene). A confident but source-contradicting answer is incorrect.

Judge against the SOURCE and REFERENCE, not outside knowledge."""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string",
                    "enum": ["correct", "partially_correct", "incorrect"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM-judge answer correctness")
    ap.add_argument("result_json", help="a run_eval.py --answers result file")
    ap.add_argument("--set", dest="golden", default="eval/golden_textgrounded.jsonl")
    ap.add_argument("--db", default=None, help="sqlite for source chunk text")
    ap.add_argument("--out", default=None, help="write judged result JSON here")
    args = ap.parse_args()

    cfg = load_config()
    from anthropic import Anthropic
    client = Anthropic()

    result = json.loads(Path(args.result_json).read_text())
    if not result.get("answers"):
        raise SystemExit("result was not produced with --answers (no answers to judge)")
    golden = {json.loads(l)["id"]: json.loads(l)
              for l in Path(args.golden).read_text().splitlines() if l.strip()}
    db = sqlite3.connect(args.db or cfg.sqlite_path)
    chunk_text = dict(db.execute("SELECT chunk_id, text FROM chunks"))

    scored = defaultdict(list)
    for row in result["per_item"]:
        gid = row["id"]
        cand = row.get("answer")
        g = golden.get(gid)
        if cand is None or g is None:
            continue
        passages = "\n\n".join(chunk_text.get(c, "") for c in g["expected_chunk_ids"])
        user = (f"QUESTION:\n{g['question']}\n\n"
                f"SOURCE PASSAGES:\n{passages}\n\n"
                f"REFERENCE ANSWER:\n{g.get('answer', '(none)')}\n\n"
                f"CANDIDATE ANSWER:\n{cand}")
        resp = client.messages.create(
            model=JUDGE_MODEL, max_tokens=512, system=SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": user}])
        txt = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            v = json.loads(txt)
        except json.JSONDecodeError:
            v = {"verdict": "incorrect", "reason": "unparseable judge output"}
        row["judge_verdict"] = v["verdict"]
        row["judge_reason"] = v["reason"]
        row["judge_score"] = SCORE[v["verdict"]]
        scored[row["qtype"]].append(row["judge_score"])
        print(f"  {gid} [{row['qtype']}] {v['verdict']}", file=sys.stderr)

    def mean(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    print("\nqtype               n   answer_correctness")
    print("-" * 44)
    allscores = []
    for qt in sorted(scored):
        allscores += scored[qt]
        print(f"{qt:18}  {len(scored[qt]):>2}   {mean(scored[qt])}")
    print("-" * 44)
    print(f"{'OVERALL':18}  {len(allscores):>2}   {mean(allscores)}")

    if args.out:
        result["judge_model"] = JUDGE_MODEL
        result["judge_overall"] = mean(allscores)
        result["judge_per_qtype"] = {qt: mean(v) for qt, v in scored.items()}
        Path(args.out).write_text(json.dumps(result, indent=1))
        print(f"\nwrote judged result -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

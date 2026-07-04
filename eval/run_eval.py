"""Evaluation runner: score retrieval (and optionally answers) on a golden set.

Usage (from the repo root):
    .venv/bin/python eval/run_eval.py --label baseline
    .venv/bin/python eval/run_eval.py --set eval/fixtures/smoke_set.jsonl --label smoke
    .venv/bin/python eval/run_eval.py --label b --limit 10 --only-qtype continuity
    .venv/bin/python eval/run_eval.py --label with-answers --answers   # costs money

Retrieval metrics are free (local embedder + local stores only). Without
--answers this never constructs an Anthropic client and never hits the network.

Writes eval/results/{YYYYMMDD-HHMMSS}_{label}.json and prints a per-qtype
summary table. Two runs with identical flags produce identical per_item
retrieval metrics; compare results with eval/compare.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import fields as dataclass_fields
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Note prefixes produced by src/retriever.py:
#   temporal/sentiment/continuity/dossier: "[Book 2, Ch 7] ..."
#   lookup:                                "[Book 2 \"Faded\", Ch 7] ..."
_NOTE_CITE_RE = re.compile(r'^\[Book (\d+)(?: "[^"]*")?, Ch (\d+)\]')

# Env-var prefixes captured into config_flags so future feature flags are
# recorded without touching this file.
_FLAG_ENV_PREFIXES = ("ENABLE_", "CONTINUITY_", "RERANK", "COST_LOG",
                      "EXTRACTION_USE", "CHUNKER_")

RETRIEVAL_METRICS = ("hit_at_k", "recall_at_k", "mrr", "citation_hit")
ALL_METRICS = RETRIEVAL_METRICS + ("router_accuracy", "n_excerpts", "n_notes",
                                   "est_prompt_tokens")


# ── loading ──────────────────────────────────────────────────────────────────

def load_items(path: Path) -> list[dict]:
    items = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}:{lineno}: invalid JSON — {e}")
    return items


def config_flags(cfg) -> dict:
    """Every bool/int/str attribute on Config (API keys redacted to set/unset),
    plus any feature-flag env vars — forward-compatible with future flags."""
    flags: dict = {}
    for f in dataclass_fields(cfg):
        value = getattr(cfg, f.name)
        if not isinstance(value, (bool, int, str)):
            continue
        if "api_key" in f.name:
            flags[f.name] = "<set>" if value else "<unset>"
        else:
            flags[f.name] = value
    for key in sorted(os.environ):
        if key.startswith(_FLAG_ENV_PREFIXES):
            flags[key] = os.environ[key]
    # the embedding model matters as much as the provider
    if os.environ.get("EMBEDDING_MODEL"):
        flags["EMBEDDING_MODEL"] = os.environ["EMBEDDING_MODEL"]
    return flags


# ── metrics ──────────────────────────────────────────────────────────────────

def note_citations(notes: list[str]) -> set[tuple[int, int]]:
    cites = set()
    for note in notes:
        m = _NOTE_CITE_RE.match(note)
        if m:
            cites.add((int(m.group(1)), int(m.group(2))))
    return cites


def est_prompt_tokens(question: str, excerpts: list[dict], notes: list[str]) -> int:
    words = len(question.split())
    words += sum(len(e["text"].split()) for e in excerpts)
    words += sum(len(n.split()) for n in notes)
    return int(words * 1.35)


def score_item(item: dict, plan, excerpts: list[dict], notes: list[str]) -> dict:
    retrieved_ids = [e["chunk_id"] for e in excerpts]
    expected_ids = item.get("expected_chunk_ids") or []

    if expected_ids:
        expected_set = set(expected_ids)
        hit = 1.0 if expected_set & set(retrieved_ids) else 0.0
        recall = len(expected_set & set(retrieved_ids)) / len(expected_set)
        mrr = 0.0
        for rank, cid in enumerate(retrieved_ids, 1):
            if cid in expected_set:
                mrr = 1.0 / rank
                break
    else:  # note-based item: chunk metrics don't apply
        hit = recall = mrr = None

    expected_cites = [tuple(c) for c in (item.get("expected_citations") or [])]
    if expected_cites:
        found = {(e.get("book_number"), e.get("chapter_number")) for e in excerpts}
        found |= note_citations(notes)
        citation_hit = sum(1 for c in expected_cites if c in found) / len(expected_cites)
    else:
        citation_hit = None

    return {
        "id": item["id"],
        "qtype": item.get("qtype", "general"),
        "router_qtype": plan.qtype,
        "router_accuracy": 1.0 if plan.qtype == item.get("qtype") else 0.0,
        "scope": item.get("scope"),
        "question": item["question"],
        "hit_at_k": hit,
        "recall_at_k": recall,
        "mrr": mrr,
        "citation_hit": citation_hit,
        "n_excerpts": len(excerpts),
        "n_notes": len(notes),
        "est_prompt_tokens": est_prompt_tokens(item["question"], excerpts, notes),
        "retrieved_chunk_ids": retrieved_ids,
    }


def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def aggregate(rows: list[dict]) -> dict:
    agg = {"n": len(rows)}
    for metric in ALL_METRICS:
        agg[metric] = _mean([r.get(metric) for r in rows])
    if any("answer_mention_hit" in r for r in rows):
        agg["answer_mention_hit"] = _mean([r.get("answer_mention_hit") for r in rows])
    return agg


# ── output ───────────────────────────────────────────────────────────────────

def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def print_table(per_qtype: dict, overall: dict) -> None:
    cols = ["qtype", "n", "hit@k", "recall", "MRR", "cite_hit", "router_acc", "tokens"]
    keys = ["hit_at_k", "recall_at_k", "mrr", "citation_hit", "router_accuracy",
            "est_prompt_tokens"]
    rows = []
    for qtype in sorted(per_qtype):
        a = per_qtype[qtype]
        rows.append([qtype, str(a["n"])] + [_fmt(a[k]) for k in keys])
    rows.append(["OVERALL", str(overall["n"])] + [_fmt(overall[k]) for k in keys])

    widths = [max(len(cols[i]), *(len(r[i]) for r in rows)) for i in range(len(cols))]
    line = "  ".join(c.ljust(w) for c, w in zip(cols, widths))
    print(line)
    print("-" * len(line))
    for r in rows[:-1]:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))
    print("-" * len(line))
    print("  ".join(c.ljust(w) for c, w in zip(rows[-1], widths)))


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Run the RAG evaluation set")
    ap.add_argument("--set", dest="set_path", default="eval/golden_set.jsonl",
                    help="path to the JSONL eval set")
    ap.add_argument("--label", required=True, help="run label (used in the filename)")
    ap.add_argument("--limit", type=int, default=None, help="only run the first N items")
    ap.add_argument("--only-qtype", default=None, help="only run items of this qtype")
    ap.add_argument("--ids", default=None, help="comma-separated item ids to run")
    ap.add_argument("--answers", action="store_true",
                    help="also generate answers via the API (costs money)")
    args = ap.parse_args()

    set_path = Path(args.set_path)
    if not set_path.is_absolute() and not set_path.exists():
        set_path = REPO_ROOT / args.set_path
    if not set_path.exists():
        print(f"Eval set not found: {set_path}")
        return 1

    items = load_items(set_path)
    if args.only_qtype:
        items = [i for i in items if i.get("qtype") == args.only_qtype]
    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        items = [i for i in items if i["id"] in wanted]
        missing = wanted - {i["id"] for i in items}
        if missing:
            print(f"warning: ids not in set: {', '.join(sorted(missing))}")
    if args.limit:
        items = items[:args.limit]
    if not items:
        print("No items to run after filtering.")
        return 1

    from config import load_config
    cfg = load_config()

    # Pin query embedding to CPU for reproducibility: on MPS (Apple GPU) the
    # embedder is nondeterministic under this workload (flips 1-3 items per
    # 40-item run at near-tie ranks), which makes zero-delta gating flaky.
    # Embedding 40 queries on CPU is cheap; production paths are unaffected.
    os.environ.setdefault("EMBEDDING_DEVICE", "cpu")

    # Heavy imports after config so log level is set (mirrors query.py wiring).
    from src.embedder import Embedder
    from src.query_router import classify
    from src.retriever import Retriever
    from src.storage import SeriesStore

    store = SeriesStore(cfg)
    if store.counts()["chunks"] == 0:
        print("The store is empty — run `python ingest.py` first.")
        return 1
    embedder = Embedder(cfg)
    retriever = Retriever(cfg, store, embedder)

    answerer = None
    if args.answers:
        # Only construct the Anthropic client when answers were asked for.
        from src.answerer import Answerer
        answerer = Answerer(cfg)

    per_item = []
    for n, item in enumerate(items, 1):
        plan = classify(item["question"])
        excerpts, notes = retriever.retrieve(plan)
        row = score_item(item, plan, excerpts, notes)

        if answerer is not None:
            import time

            from src.costlog import log_cost
            usage_before = dict(answerer.usage)
            cost_before = answerer.actual_cost_usd
            t0 = time.monotonic()
            answer_text = answerer.answer(plan, excerpts, notes)
            row["answer"] = answer_text
            row["usage"] = {k: answerer.usage[k] - usage_before[k]
                            for k in answerer.usage}
            row["actual_cost_usd"] = round(answerer.actual_cost_usd - cost_before, 4)
            log_cost(cfg, surface="eval", model=answerer.model, qtype=plan.qtype,
                     usage=row["usage"], cost_usd=row["actual_cost_usd"],
                     latency_ms=int((time.monotonic() - t0) * 1000),
                     extra={"item_id": item["id"], "label": args.label})
            must = item.get("answer_must_mention") or []
            row["answer_mention_hit"] = (
                sum(1 for m in must if m.lower() in answer_text.lower()) / len(must)
                if must else None)

        per_item.append(row)
        print(f"[{n}/{len(items)}] {item['id']} "
              f"({row['qtype']} -> {row['router_qtype']}) "
              f"hit={_fmt(row['hit_at_k'])} cite={_fmt(row['citation_hit'])}",
              file=sys.stderr)

    by_qtype: dict[str, list[dict]] = {}
    for row in per_item:
        by_qtype.setdefault(row["qtype"], []).append(row)
    per_qtype = {qt: aggregate(rows) for qt, rows in by_qtype.items()}
    overall = aggregate(per_item)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    result = {
        "label": args.label,
        "timestamp": timestamp,
        "set": str(set_path),
        "answers": bool(args.answers),
        "config_flags": config_flags(cfg),
        "per_item": per_item,
        "aggregates": {"overall": overall, "per_qtype": per_qtype},
    }
    if answerer is not None:
        result["total_usage"] = answerer.usage
        result["total_cost_usd"] = answerer.actual_cost_usd

    results_dir = REPO_ROOT / "eval" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{timestamp}_{args.label}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    print()
    print_table(per_qtype, overall)
    print(f"\nwrote {out_path}")
    if answerer is not None:
        print(f"answer cost: ${answerer.actual_cost_usd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

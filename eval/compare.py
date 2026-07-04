"""Compare two eval runs produced by eval/run_eval.py.

Usage:
    python eval/compare.py eval/results/A.json eval/results/B.json
    python eval/compare.py A.json B.json --allow-regressions

Prints per-qtype aggregate deltas (B minus A), any per-item retrieval
regressions (hit@k / recall@k / MRR / citation_hit decreased in B), and a
diff of the two runs' config_flags. Exits 1 if any per-item retrieval metric
regressed (usable as a CI/gate), 0 otherwise; --allow-regressions forces 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RETRIEVAL_METRICS = ("hit_at_k", "recall_at_k", "mrr", "citation_hit")
AGG_METRICS = RETRIEVAL_METRICS + ("router_accuracy", "n_excerpts", "n_notes",
                                   "est_prompt_tokens", "answer_mention_hit")


def load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:+.3f}" if v else "0"
    return str(v)


def _delta(a, b):
    if a is None and b is None:
        return None
    if a is None or b is None:
        return f"{_val(a)} -> {_val(b)}"
    return round(b - a, 4)


def _val(v) -> str:
    return "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def print_aggregate_deltas(agg_a: dict, agg_b: dict) -> None:
    qtypes = sorted(set(agg_a.get("per_qtype", {})) | set(agg_b.get("per_qtype", {})))
    sections = [("OVERALL", agg_a.get("overall", {}), agg_b.get("overall", {}))]
    sections += [(qt, agg_a["per_qtype"].get(qt, {}), agg_b["per_qtype"].get(qt, {}))
                 for qt in qtypes]

    print("== Aggregate deltas (B - A) ==")
    header = f"{'qtype':<20}{'n(A/B)':<10}" + "".join(
        f"{m:<20}" for m in AGG_METRICS)
    print(header)
    print("-" * len(header))
    for name, a, b in sections:
        cells = [f"{name:<20}", f"{a.get('n', '-')}/{b.get('n', '-')}".ljust(10)]
        for m in AGG_METRICS:
            d = _delta(a.get(m), b.get(m))
            cells.append(f"{_fmt(d):<20}" if not isinstance(d, str) else f"{d:<20}")
        print("".join(cells))
    print()


def find_regressions(a: dict, b: dict) -> list[dict]:
    items_a = {r["id"]: r for r in a["per_item"]}
    items_b = {r["id"]: r for r in b["per_item"]}
    regressions = []
    for item_id in sorted(set(items_a) & set(items_b)):
        ra, rb = items_a[item_id], items_b[item_id]
        drops = {}
        for m in RETRIEVAL_METRICS:
            va, vb = ra.get(m), rb.get(m)
            if va is not None and vb is not None and vb < va:
                drops[m] = (va, vb)
        if drops:
            regressions.append({"id": item_id, "qtype": ra.get("qtype"),
                                "drops": drops})
    return regressions


def print_flag_diff(flags_a: dict, flags_b: dict) -> None:
    print("== Config flag diff ==")
    keys = sorted(set(flags_a) | set(flags_b))
    diffs = [(k, flags_a.get(k, "<missing>"), flags_b.get(k, "<missing>"))
             for k in keys if flags_a.get(k, "<missing>") != flags_b.get(k, "<missing>")]
    if not diffs:
        print("(identical)")
    else:
        for key, va, vb in diffs:
            print(f"  {key}: {va!r} -> {vb!r}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare two eval result files")
    ap.add_argument("result_a", help="baseline result JSON (A)")
    ap.add_argument("result_b", help="candidate result JSON (B)")
    ap.add_argument("--allow-regressions", action="store_true",
                    help="exit 0 even if per-item retrieval metrics regressed")
    args = ap.parse_args()

    a, b = load(args.result_a), load(args.result_b)
    print(f"A: {a.get('label')} ({a.get('timestamp')})")
    print(f"B: {b.get('label')} ({b.get('timestamp')})\n")

    print_flag_diff(a.get("config_flags", {}), b.get("config_flags", {}))
    print_aggregate_deltas(a.get("aggregates", {}), b.get("aggregates", {}))

    only_a = {r["id"] for r in a["per_item"]} - {r["id"] for r in b["per_item"]}
    only_b = {r["id"] for r in b["per_item"]} - {r["id"] for r in a["per_item"]}
    if only_a:
        print(f"items only in A: {', '.join(sorted(only_a))}")
    if only_b:
        print(f"items only in B: {', '.join(sorted(only_b))}")

    regressions = find_regressions(a, b)
    print("== Per-item regressions (B worse than A) ==")
    if not regressions:
        print("(none)")
    else:
        for r in regressions:
            drops = ", ".join(f"{m} {va:.3f} -> {vb:.3f}"
                              for m, (va, vb) in r["drops"].items())
            print(f"  {r['id']} [{r['qtype']}]: {drops}")

    if regressions and not args.allow_regressions:
        print(f"\nFAIL: {len(regressions)} item(s) regressed")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

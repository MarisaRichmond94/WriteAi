"""Query CLI — ask questions of the ingested series.

Usage:
    python query.py "What does Aria know about the Vault at the end of book 2?"
    python query.py --scope "book:1-3" "Are there any unresolved plot threads?"
    python query.py --scope "book:2,chapter:5" "How does Marcus feel about Elena?"
    python query.py --type continuity "Do you see any plot holes?"
    python query.py --export character_timeline "Jared Gatlin"
    python query.py --export relationship_map "Jared Gatlin" "Noah Gatlin"

Reads only the local stores; the single API call per question goes to
QUERY_MODEL. Cost for the call is printed at the end.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from config import load_config


def main() -> int:
    ap = argparse.ArgumentParser(description="Ask questions of the series")
    ap.add_argument("question", nargs="*", help="the question to answer")
    ap.add_argument("--scope", help='e.g. "book:1-3" or "book:2,chapter:5"')
    ap.add_argument("--type", dest="qtype",
                    choices=["temporal_knowledge", "sentiment", "continuity",
                             "lookup", "general"],
                    help="force a query type instead of auto-classifying")
    ap.add_argument("--export", choices=["character_timeline", "relationship_map"])
    ap.add_argument("--top-k", type=int, default=None,
                    help="override TOP_K_RESULTS for this query")
    ap.add_argument("--show-plan", action="store_true",
                    help="print the retrieval plan before answering")
    args = ap.parse_args()

    cfg = load_config()
    if args.top_k:
        cfg.top_k_results = args.top_k

    # Heavy imports after arg parsing so --help stays instant.
    from src.answerer import Answerer
    from src.embedder import Embedder
    from src.query_router import QueryPlan, classify
    from src.retriever import Retriever
    from src.storage import SeriesStore

    store = SeriesStore(cfg)
    if store.counts()["chunks"] == 0:
        print("The store is empty — run `python ingest.py` first.")
        return 1
    embedder = Embedder(cfg)
    retriever = Retriever(cfg, store, embedder)
    answerer = Answerer(cfg)

    if args.export:
        names = args.question
        needed = 2 if args.export == "relationship_map" else 1
        if len(names) < needed:
            print(f"--export {args.export} needs {needed} character name(s)")
            return 1
        if args.export == "character_timeline":
            notes = retriever.character_dossier(names[0])
        else:
            notes = retriever.character_dossier(names[0], require_all=names[:2])
        if not notes:
            print(f"No ingested scenes found for {', '.join(names[:needed])}.")
            return 1
        # a few anchoring excerpts via semantic search on the names
        plan = QueryPlan(question=" and ".join(names[:needed]), qtype="general")
        excerpts, _ = retriever.retrieve(plan)
        t0 = time.monotonic()
        print(answerer.export(args.export, names, notes, excerpts[:6]))
    else:
        if not args.question:
            print("No question given.")
            return 1
        question = " ".join(args.question)
        plan = classify(question, args.scope, args.qtype)
        if args.show_plan:
            print(f"[plan] type={plan.qtype} scope={plan.scope.describe()} "
                  f"characters={plan.characters}\n")
        excerpts, notes = retriever.retrieve(plan)
        t0 = time.monotonic()
        print(answerer.answer(plan, excerpts, notes))

    print(f"\n---\n[{answerer.model}: {answerer.usage['input_tokens']:,} in / "
          f"{answerer.usage['output_tokens']:,} out tokens, "
          f"${answerer.actual_cost_usd}]")
    from src.costlog import log_cost
    log_cost(cfg, surface="cli-query", model=answerer.model, qtype=plan.qtype,
             usage=answerer.usage, cost_usd=answerer.actual_cost_usd,
             latency_ms=int((time.monotonic() - t0) * 1000),
             extra={"export": args.export} if args.export else None)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())

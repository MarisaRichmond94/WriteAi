"""Append-only API spend ledger: logs/cost.jsonl.

One JSON line per model request (or per run for batch surfaces like ingest
and enrichment) with tokens, dollars, latency, and the feature flags in
effect — the place to look when the monthly bill needs explaining. Same
location and idiom as server/audit.py: module lock, best-effort append,
never raises into the request it describes.

Disabled by setting COST_LOG_ENABLED=false (cfg.cost_log_enabled).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone

from config import REPO_ROOT

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_PATH = REPO_ROOT / "logs" / "cost.jsonl"

# Feature-flag env vars worth stamping on every line, so A/B comparisons of
# cost/quality across flag settings stay possible after the fact.
_FLAG_PREFIXES = ("ENABLE_", "CONTINUITY_", "RERANK", "COST_LOG",
                  "EXTRACTION_USE", "CHUNKER_")


def usage_diff(after: dict, before: dict) -> dict:
    """Per-request usage from an Answerer's CUMULATIVE counters: snapshot
    `dict(answerer.usage)` before the call, diff after."""
    return {k: after[k] - before.get(k, 0) for k in after}


def log_cost(cfg, *, surface: str, model: str, qtype: str | None = None,
             usage: dict, cost_usd: float, latency_ms: int | None = None,
             extra: dict | None = None) -> None:
    """Best-effort: a cost-log failure must never break the request it
    describes. No-op when cfg.cost_log_enabled is false."""
    try:
        if not getattr(cfg, "cost_log_enabled", True):
            return
        entry = {
            "at": datetime.now(timezone.utc).isoformat(),
            "surface": surface,  # cli-query|chat|review|enrich|ingest|eval
            "model": model,
            "qtype": qtype,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_write_tokens": usage.get("cache_write_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_tokens", 0),
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "flags": {k: v for k, v in sorted(os.environ.items())
                      if k.startswith(_FLAG_PREFIXES)},
            **(extra or {}),
        }
        with _LOCK:
            _PATH.parent.mkdir(exist_ok=True)
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        log.warning("cost log write to %s failed", _PATH, exc_info=True)

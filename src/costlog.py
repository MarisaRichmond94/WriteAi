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
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from config import REPO_ROOT

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_PATH = REPO_ROOT / "logs" / "cost.jsonl"

# Feature-flag env vars worth stamping on every line, so A/B comparisons of
# cost/quality across flag settings stay possible after the fact.
_FLAG_PREFIXES = ("ENABLE_", "CONTINUITY_", "RERANK", "COST_LOG",
                  "EXTRACTION_USE", "CHUNKER_", "PROMPT_CACHE_TTL")


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


@contextmanager
def cost_scope(cfg, *, surface: str, answerer, qtype: str | None = None,
               extra: dict | None = None):
    """Ledger one streamed request — whether it finishes, fails, or the reader
    closes the tab on it.

    The API bills for everything it processed before a stream died, so the
    line is written from a `finally`. Logging only on the happy path (the
    original shape) meant a mid-stream read timeout wrote nothing at all: the
    spend dashboard showed $0 for a request that really cost input, cache
    writes, and whatever output had already been generated.

    Every line carries `state`: done | failed | aborted, with `error` naming
    the failure — so a surface's ledger total can be split into spend the
    writer got something for and spend she didn't.
    """
    u0 = dict(answerer.usage)
    c0 = answerer.actual_cost_usd
    t0 = time.monotonic()
    state, err = "done", None
    try:
        yield
    except GeneratorExit:               # client hung up mid-stream
        state, err = "aborted", "client disconnected"
        raise
    except BaseException as e:
        state, err = "failed", f"{type(e).__name__}: {e}"
        raise
    finally:
        log_cost(cfg, surface=surface, model=answerer.model, qtype=qtype,
                 usage=usage_diff(answerer.usage, u0),
                 cost_usd=round(answerer.actual_cost_usd - c0, 4),
                 latency_ms=int((time.monotonic() - t0) * 1000),
                 extra={**(extra or {}), "state": state,
                        **({"error": err} if err else {})})

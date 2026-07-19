"""Daily spend metrics from the cost ledger (logs/cost.jsonl).

Read-only aggregation over the append-only ledger written by src/costlog.py.
Each ledger line already carries a precomputed `cost_usd`, a `surface`, token
counts, and an ISO `at` timestamp, so this router never touches the model or
recomputes pricing — it just buckets lines by day and by category.

The dashboard's four categories map onto ledger `surface` values:

    sync         <- ingest
    enrichment   <- enrich, chronology, locations_v2
    exploration  <- chat, cli-query
    reviews      <- review

`eval` lines (offline benchmark runs) are deliberately excluded; any surface
we don't recognise is bucketed as "other" so new instrumentation still shows
up in the grand total instead of silently vanishing.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query

from config import REPO_ROOT

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_LEDGER = REPO_ROOT / "logs" / "cost.jsonl"

# surface -> dashboard category. Surfaces absent here fall through to "other";
# "eval" is excluded entirely (offline benchmark noise, not real spend).
SURFACE_TO_CATEGORY = {
    "ingest": "sync",
    "enrich": "enrichment",
    "chronology": "enrichment",
    "locations_v2": "enrichment",
    "chat": "exploration",
    "cli-query": "exploration",
    "review": "reviews",
}
EXCLUDED_SURFACES = {"eval"}
CATEGORIES = ["sync", "enrichment", "exploration", "reviews", "other"]


def _empty_bucket() -> dict:
    return {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "calls": 0}


def _accumulate(bucket: dict, entry: dict) -> None:
    bucket["cost_usd"] += entry.get("cost_usd") or 0.0
    bucket["input_tokens"] += entry.get("input_tokens") or 0
    bucket["output_tokens"] += entry.get("output_tokens") or 0
    # Batch surfaces (ingest/enrich) log one line per run with an api_calls
    # count; single-request surfaces omit it and count as one call.
    bucket["calls"] += entry.get("api_calls") or 1


@router.get("/metrics/spend")
def spend(days: int = Query(30, ge=1, le=365)):
    """Per-day spend for the trailing `days` days, split by category.

    Days are bucketed in the server's local timezone (the machine that ran the
    work), so "today" lines up with the writer's calendar rather than UTC.
    Returns a continuous date series (zero-filled) so a chart has no gaps.
    """
    today = datetime.now().astimezone().date()
    start = today - timedelta(days=days - 1)

    # date -> category -> bucket, and category -> bucket (window totals)
    by_day: dict[date, dict[str, dict]] = defaultdict(
        lambda: {c: _empty_bucket() for c in CATEGORIES})
    totals: dict[str, dict] = {c: _empty_bucket() for c in CATEGORIES}
    models: dict[str, dict] = defaultdict(_empty_bucket)  # model -> bucket

    if _LEDGER.exists():
        with open(_LEDGER, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue  # tolerate a torn final line mid-append
                surface = entry.get("surface")
                if surface in EXCLUDED_SURFACES:
                    continue
                at = entry.get("at")
                if not at:
                    continue
                try:
                    day = datetime.fromisoformat(at).astimezone().date()
                except ValueError:
                    continue
                if day < start or day > today:
                    continue
                category = SURFACE_TO_CATEGORY.get(surface, "other")
                _accumulate(by_day[day][category], entry)
                _accumulate(totals[category], entry)
                _accumulate(models[entry.get("model") or "unknown"], entry)

    daily = []
    cursor = start
    while cursor <= today:
        buckets = by_day.get(cursor)
        row = {"date": cursor.isoformat()}
        day_total = 0.0
        for c in CATEGORIES:
            cost = round(buckets[c]["cost_usd"], 6) if buckets else 0.0
            row[c] = cost
            day_total += cost
        row["total"] = round(day_total, 6)
        daily.append(row)
        cursor += timedelta(days=1)

    def _round(bucket: dict) -> dict:
        return {**bucket, "cost_usd": round(bucket["cost_usd"], 6)}

    grand_total = round(sum(b["cost_usd"] for b in totals.values()), 6)

    return {
        "days": days,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "categories": [c for c in CATEGORIES if c != "other"] + ["other"],
        "daily": daily,
        "totals": {c: _round(totals[c]) for c in CATEGORIES},
        "by_model": {m: _round(b) for m, b in sorted(
            models.items(), key=lambda kv: -kv[1]["cost_usd"])},
        "grand_total_usd": grand_total,
    }

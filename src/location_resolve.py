"""Book-scoped location gazetteer (ENABLE_LOCATION_V2).

The v1 gazetteer (location_map) keys each raw extracted string once for the
whole series, so a character who moves between books collapses two homes into
one venue: Book 5's "Jared's apartment" absorbed Book 1's "Jared's bedroom"
even though Book 1's own raw strings say "Jared's house". This module resolves
each (book, raw) pair instead, using only that book's evidence for dwelling
type, and fixes two more v1 losses:

  * hierarchy gains a third level — a SETTLEMENT may name its wider region
    as parent ("Dead Falls" -> "Los Angeles area, California") — so the
    Locations pane can show region > settlement > venue;
  * the sub-venue spot ("bedroom", "porch") is kept as `area` instead of
    being discarded when sub-areas collapse to their venue;
  * anchored generic references ("the town" the main cast lives in) backfill
    to the canonical place once the series establishes it, so Book 1 chapters
    written before the town is named still resolve.

Books resolve in order and share a growing known-places context (each place
annotated with the books it has appeared in), which keeps spelling consistent
without letting a later book's venue hijack an earlier book's strings.

Rows are upserted into location_map_v2; the v1 table is never touched, so the
flag can be turned off at any time. Per-book completion is recorded in
enrich_state (scope "locmap_v2:<book>") keyed by a hash of that book's raw
strings, which is how both the enrichment runner and the standalone script
(scripts/resolve_locations.py) skip books whose inputs have not changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time

from src.costlog import log_cost
from src.extractor import PRICING_PER_MTOK

log = logging.getLogger(__name__)

BATCH_SIZE = 100

# Included in every state hash so a prompt change re-resolves on the next run.
_PROMPT_V = "locmap-v2.1"

SYSTEM_PROMPT = """You are normalizing location strings extracted from ONE BOOK of a fiction series into a clean gazetteer. You get the book number, that book's raw strings, and known_places already established elsewhere in the series (each with the books it has appeared in).

For each raw string, return:
- place: the canonical location at one of exactly two granularities —
  a SETTLEMENT (town, city, e.g. "Los Angeles") or a VENUE (a specific home,
  school, business, or landmark, e.g. "Emma's house", "Crestwood High School").
- area: the sub-venue spot the raw string names, or null. Sub-areas collapse
  to their venue but keep the spot: "Emma's house - porch" -> place
  "Emma's house", area "porch"; "gym at Crestwood High" -> place
  "Crestwood High School", area "gym".
- parent: for a VENUE, the settlement it is in when the strings make that
  clear; for a SETTLEMENT, the wider region when the series establishes one
  (e.g. "Dead Falls" -> "Los Angeles area, California"); null otherwise.
- place = null for NON-places and unusable fragments: phone/video calls,
  events described as places, vehicles and driving, roads and highways,
  street addresses with no named venue, and generic unanchored rooms
  ("a basement room", "a dark alleyway"). A missing location is better
  than a bad one.

RESIDENCES CHANGE OVER TIME — this book's evidence wins. A possessive
residence string ("Jared's bedroom", "Emma's home") resolves to the dwelling
THIS book's raw strings support: if this book says "Jared's house", then
"Jared's bedroom" belongs here to the canonical place "Jared's house" —
prefer the specific dwelling the book names over vaguer forms like
"Jared's home", even when another book already established the vague form.
Never merge a house and an apartment into one venue just because the owner's
name matches, and never guess the dwelling type: when this book has no
evidence either way, copy the known place from the nearest book if one
exists, otherwise use the neutral "X's home".

ANCHORED GENERICS: a generic reference that unmistakably means an established
known place resolves to that place even if this book never says its name —
series knowledge backfills earlier books: "the town" the main cast lives in
resolves to that town; a bare "school" or "the high school" resolves to the
school the cast attends when exactly one is known. Only do this when exactly
one known place fits; otherwise null.

CONSISTENCY: when a raw string refers to a known place, copy its name
EXACTLY. Never invent multiple spellings of the same place."""

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"mappings": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "raw": {"type": "string"},
            "place": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "parent": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "area": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["raw", "place", "parent", "area"],
        "additionalProperties": False,
    }}},
    "required": ["mappings"],
    "additionalProperties": False,
}


REGION_PROMPT = """You are assigning each SETTLEMENT from a fiction series to its wider region, completing the top level of a region > settlement > venue gazetteer.

You get the settlements (each with the books it appears in), sample raw location strings that mention them, and short prose sentences from the manuscripts that mention them — the prose is where geography is usually anchored ("a small town outside Los Angeles").

For each settlement return region: the wider real or fictional area the series places it in, phrased naturally (e.g. "Los Angeles area, California"), or null when neither strings nor prose give an anchor. Use ONE consistent region name for settlements placed in the same area, and never invent geography the material does not support — null is better than a guess."""

VENUE_PARENT_PROMPT = """You are placing VENUES from a fiction series into their SETTLEMENTS, completing the middle level of a region > settlement > venue gazetteer.

You get the venues that have no settlement yet (each with the books it appears in, sample raw location strings, and short prose sentences that mention it) and the series' established settlements.

For each venue return settlement: the settlement it is in, copied EXACTLY from the settlements list, or null. Use the judgment of a careful reader of the whole series: the main cast's homes, school, and hangouts are in the settlement where their daily life happens, even when no single string says so — a school named after a town is in that town. Return null only when the venue is genuinely elsewhere, ambiguous between settlements, or too generic to place. Never use a settlement that is not in the list."""

_VENUE_PARENT_SCHEMA = {
    "type": "object",
    "properties": {"venues": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "venue": {"type": "string"},
            "settlement": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["venue", "settlement"],
        "additionalProperties": False,
    }}},
    "required": ["venues"],
    "additionalProperties": False,
}

_REGION_SCHEMA = {
    "type": "object",
    "properties": {"settlements": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "settlement": {"type": "string"},
            "region": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["settlement", "region"],
        "additionalProperties": False,
    }}},
    "required": ["settlements"],
    "additionalProperties": False,
}


def ensure_table(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS location_map_v2 (
            book_number INTEGER NOT NULL,
            raw TEXT NOT NULL,
            place TEXT,
            parent TEXT,
            area TEXT,
            PRIMARY KEY (book_number, raw)
        )""")
    db.execute("""
        CREATE TABLE IF NOT EXISTS enrich_state (
            scope TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL
        )""")
    db.commit()


def book_inputs(db: sqlite3.Connection) -> dict[int, list[str]]:
    """Distinct raw location strings per book, in book order."""
    by_book: dict[int, list[str]] = {}
    for book, raw in db.execute(
            """SELECT DISTINCT c.book_number, l.name
               FROM locations l JOIN chunks c ON c.chunk_id = l.chunk_id
               ORDER BY c.book_number, l.name"""):
        by_book.setdefault(book, []).append(raw)
    return by_book


def book_hash(raws: list[str]) -> str:
    return hashlib.sha256(json.dumps([_PROMPT_V, raws]).encode()).hexdigest()


def pending_books(db: sqlite3.Connection) -> dict[int, list[str]]:
    """Books whose raw-string set differs from their recorded resolution."""
    done = dict(db.execute(
        "SELECT scope, content_hash FROM enrich_state "
        "WHERE scope LIKE 'locmap_v2:%'"))
    return {b: raws for b, raws in book_inputs(db).items()
            if done.get(f"locmap_v2:{b}") != book_hash(raws)}


_SENT_SPLIT = re.compile(r"(?<=[.!?”\"])\s+")


# A sentence that anchors a settlement geographically almost always names
# other geography alongside it; a bare mention ("that's the problem with
# Dead Falls") never does. Used to rank candidate sentences.
_GEO_HINTS = ("town", "city", "county", "state", "north", "south", "east",
              "west", "miles", "outside", "near", "between", "area", "suburb",
              "coast", "valley", "hills", "highway", "drive from", "trek")


def _prose_mentions(db: sqlite3.Connection, name: str, others: list[str],
                    cap: int = 5) -> list[str]:
    """Up to `cap` distinct manuscript sentences naming `name`, geography-
    rich ones first — the region anchor is usually prose, never a location
    string, and rarely in the earliest mention."""
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for order, (text,) in enumerate(db.execute(
            "SELECT text FROM chunks WHERE text LIKE ? LIMIT 200",
            (f"%{name}%",))):
        for s in _SENT_SPLIT.split(text):
            s = s.strip()
            if name not in s or s in seen:
                continue
            seen.add(s)
            low = s.lower()
            score = (sum(h in low for h in _GEO_HINTS)
                     + 2 * sum(o in s for o in others if o != name))
            scored.append((-score, order, s[:300]))
    return [s for _, _, s in sorted(scored)[:cap]]


def _settlements(db: sqlite3.Connection) -> list[str]:
    """Places some other place names as parent — the settlement tier."""
    return sorted({p for (p,) in db.execute(
        "SELECT DISTINCT parent FROM location_map_v2 "
        "WHERE parent IS NOT NULL AND parent != ''")})


def _resolve_parents(db: sqlite3.Connection, cfg, client, usage: dict) -> int:
    """Fill venue -> settlement parents left null by the per-book pass.

    The per-book resolver only sets a parent its batch's strings prove, so
    the cast's own homes and school usually come out parentless ("Jared's
    house" — no string says which town a house is in). This pass sees every
    settlement plus prose mentions and is allowed a careful reader's
    judgment; answers are validated against the settlement list, so it can
    place venues but never invent geography. Only empty parents are filled;
    skipped via enrich_state (scope "locmap_v2:parents") on unchanged
    inputs."""
    settlements = _settlements(db)
    if not settlements:
        return 0
    venues = [p for (p,) in db.execute(
        "SELECT DISTINCT place FROM location_map_v2 WHERE place IS NOT NULL "
        "AND (parent IS NULL OR parent = '') ORDER BY place")
        if p not in settlements]
    if not venues:
        return 0
    payload = []
    for v in venues:
        payload.append({
            "venue": v,
            "books": [b for (b,) in db.execute(
                "SELECT DISTINCT book_number FROM location_map_v2 "
                "WHERE place = ? ORDER BY 1", (v,))],
            "sample_strings": [r[0] for r in db.execute(
                "SELECT DISTINCT raw FROM location_map_v2 "
                "WHERE place = ? LIMIT 6", (v,))],
            "prose_mentions": _prose_mentions(db, v, settlements, cap=3),
        })
    h = hashlib.sha256(json.dumps(
        [VENUE_PARENT_PROMPT, settlements, payload], ensure_ascii=False,
        sort_keys=True).encode()).hexdigest()
    row = db.execute("SELECT content_hash FROM enrich_state "
                     "WHERE scope = 'locmap_v2:parents'").fetchone()
    if row and row[0] == h:
        return 0
    n = 0
    valid = set(settlements)
    for i in range(0, len(payload), 80):
        r = client.messages.create(
            model=cfg.extraction_model, max_tokens=8000,
            system=VENUE_PARENT_PROMPT,
            output_config={"format": {"type": "json_schema",
                                      "schema": _VENUE_PARENT_SCHEMA}},
            messages=[{"role": "user", "content": json.dumps({
                "settlements": settlements,
                "venues": payload[i:i + 80],
            }, ensure_ascii=False)}])
        usage["input_tokens"] += r.usage.input_tokens
        usage["output_tokens"] += r.usage.output_tokens
        usage["api_calls"] += 1
        if r.stop_reason in ("refusal", "max_tokens"):
            raise RuntimeError(f"venue-parent call ended with {r.stop_reason}")
        data = json.loads(next(b.text for b in r.content if b.type == "text"))
        batch_venues = {p["venue"] for p in payload[i:i + 80]}
        for m in data.get("venues", []):
            s = m.get("settlement")
            if (m.get("venue") in batch_venues and s in valid
                    and s != m["venue"]):
                n += db.execute(
                    "UPDATE location_map_v2 SET parent = ? "
                    "WHERE place = ? AND (parent IS NULL OR parent = '')",
                    (s, m["venue"])).rowcount
        db.commit()
    db.execute("INSERT INTO enrich_state (scope, content_hash) VALUES "
               "('locmap_v2:parents', ?) ON CONFLICT(scope) DO UPDATE SET "
               "content_hash = excluded.content_hash", (h,))
    db.commit()
    return n


def _resolve_regions(db: sqlite3.Connection, cfg, client, usage: dict) -> int:
    """Fill settlement -> region parents (the gazetteer's top level).

    Settlements are places some venue named as parent; a single call sees
    them all with sample strings from every book, since the anchor that ties
    a settlement to its region ("between Dead Falls and Bakersfield",
    "western Los Angeles") is usually in a different book than the one that
    established the settlement. Only rows whose parent is still empty are
    updated, so a region never overrides a more specific parent. Skipped via
    enrich_state (scope "locmap_v2:regions") when the settlement set and
    prompt are unchanged."""
    settlements = _settlements(db)
    if not settlements:
        return 0
    payload = []
    for s in settlements:
        payload.append({
            "settlement": s,
            "books": [b for (b,) in db.execute(
                "SELECT DISTINCT book_number FROM location_map_v2 "
                "WHERE place = ? OR parent = ? ORDER BY 1", (s, s))],
            "sample_strings": [r[0] for r in db.execute(
                "SELECT DISTINCT raw FROM location_map_v2 "
                "WHERE raw LIKE ? LIMIT 10", (f"%{s}%",))],
            "prose_mentions": _prose_mentions(db, s, settlements),
        })
    # hash the payload itself: prompt tweaks, new settlements, and better
    # prose sampling all re-trigger the pass; identical inputs never do
    h = hashlib.sha256(json.dumps(
        [REGION_PROMPT, payload], ensure_ascii=False,
        sort_keys=True).encode()).hexdigest()
    row = db.execute("SELECT content_hash FROM enrich_state "
                     "WHERE scope = 'locmap_v2:regions'").fetchone()
    if row and row[0] == h:
        return 0
    r = client.messages.create(
        model=cfg.extraction_model, max_tokens=4000, system=REGION_PROMPT,
        output_config={"format": {"type": "json_schema",
                                  "schema": _REGION_SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(
            {"settlements": payload}, ensure_ascii=False)}])
    usage["input_tokens"] += r.usage.input_tokens
    usage["output_tokens"] += r.usage.output_tokens
    usage["api_calls"] += 1
    if r.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"region call ended with {r.stop_reason}")
    data = json.loads(next(b.text for b in r.content if b.type == "text"))
    valid = set(settlements)
    n = 0
    for m in data.get("settlements", []):
        region = m.get("region")
        if m.get("settlement") in valid and region and region != m["settlement"]:
            n += db.execute(
                "UPDATE location_map_v2 SET parent = ? "
                "WHERE place = ? AND (parent IS NULL OR parent = '')",
                (region, m["settlement"])).rowcount
    db.execute("INSERT INTO enrich_state (scope, content_hash) VALUES "
               "('locmap_v2:regions', ?) ON CONFLICT(scope) DO UPDATE SET "
               "content_hash = excluded.content_hash", (h,))
    db.commit()
    return n


def _backfill_inputs(db: sqlite3.Connection) -> dict[int, list[str]]:
    """(book, raw) pairs with no resolved place: mapped to null, or dropped
    from a model response entirely."""
    have = {(b, r) for b, r in db.execute(
        "SELECT book_number, raw FROM location_map_v2 "
        "WHERE place IS NOT NULL")}
    return {book: missing for book, raws in book_inputs(db).items()
            if (missing := [r for r in raws if (book, r) not in have])}


def _backfill_hash(todo: dict[int, list[str]]) -> str:
    return hashlib.sha256(json.dumps(
        [SYSTEM_PROMPT, sorted(todo.items())]).encode()).hexdigest()


def _backfill_unmapped(db: sqlite3.Connection, cfg, client,
                       known: dict[str, dict], usage: dict) -> int:
    """Retry unresolved raws now that every book's places are known.

    Book 1 resolves before any later book has named the school or the town,
    so its anchored generics ("school", "the town") can only backfill once
    the series-wide known map exists. Most nulls are legitimately null
    (vehicles, phone calls) and simply stay null; the recorded state is the
    hash of the raws still unresolved AFTER the sweep, so an unchanged
    residue is never retried."""
    todo = _backfill_inputs(db)
    if not todo:
        return 0
    row = db.execute("SELECT content_hash FROM enrich_state "
                     "WHERE scope = 'locmap_v2:backfill'").fetchone()
    if row and row[0] == _backfill_hash(todo):
        return 0
    n = 0
    for book in sorted(todo):
        raws = todo[book]
        for i in range(0, len(raws), BATCH_SIZE):
            batch = raws[i:i + BATCH_SIZE]
            r = client.messages.create(
                model=cfg.extraction_model, max_tokens=8000,
                system=SYSTEM_PROMPT,
                output_config={"format": {"type": "json_schema",
                                          "schema": _OUTPUT_SCHEMA}},
                messages=[{"role": "user", "content": json.dumps({
                    "book_number": book,
                    "known_places": [
                        {"place": k, "parent": v["parent"],
                         "books": sorted(v["books"])}
                        for k, v in sorted(known.items())],
                    "locations": batch,
                }, ensure_ascii=False)}])
            usage["input_tokens"] += r.usage.input_tokens
            usage["output_tokens"] += r.usage.output_tokens
            usage["api_calls"] += 1
            if r.stop_reason in ("refusal", "max_tokens"):
                raise RuntimeError(f"backfill call ended with {r.stop_reason}")
            data = json.loads(
                next(b.text for b in r.content if b.type == "text"))
            valid = set(batch)
            for m in data.get("mappings", []):
                place = m.get("place")
                if m.get("raw") not in valid or not place:
                    continue
                parent = m.get("parent")
                entry = known.setdefault(
                    place, {"parent": parent, "books": set()})
                entry["books"].add(book)
                if parent and not entry["parent"]:
                    entry["parent"] = parent
                db.execute(
                    """INSERT INTO location_map_v2
                           (book_number, raw, place, parent, area)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(book_number, raw) DO UPDATE SET
                           place = excluded.place, parent = excluded.parent,
                           area = excluded.area""",
                    (book, m["raw"], place, parent, m.get("area")))
                n += 1
            db.commit()
    db.execute("INSERT INTO enrich_state (scope, content_hash) VALUES "
               "('locmap_v2:backfill', ?) ON CONFLICT(scope) DO UPDATE SET "
               "content_hash = excluded.content_hash",
               (_backfill_hash(_backfill_inputs(db)),))
    db.commit()
    return n


def _known_places(db: sqlite3.Connection,
                  exclude: set[int]) -> dict[str, dict]:
    """place -> {parent, books} from already-resolved books."""
    known: dict[str, dict] = {}
    for book, place, parent in db.execute(
            "SELECT book_number, place, parent FROM location_map_v2 "
            "WHERE place IS NOT NULL ORDER BY book_number"):
        if book in exclude:
            continue
        entry = known.setdefault(place, {"parent": parent, "books": set()})
        entry["books"].add(book)
        if parent and not entry["parent"]:
            entry["parent"] = parent
    return known


def resolve_locations(db: sqlite3.Connection, cfg, client, *,
                      books: set[int] | None = None,
                      on_batch=None, stats: dict | None = None) -> dict:
    """Resolve (book, raw) -> (place, parent, area) for `books` (default:
    every book with unresolved/changed inputs) and upsert into
    location_map_v2.

    Books resolve in ascending order sharing a growing known-places context.
    A book's enrich_state scope is only advanced when every one of its
    batches succeeded, so a partial failure re-resolves that book next run.

    on_batch(book, n_mapped) is called after each batch is written. `stats`
    (updated in place) gains: usage, upserts, books_resolved, failed_batches,
    cost_usd. Cost is logged to the "locations_v2" surface."""
    ensure_table(db)
    stats = stats if stats is not None else {}
    usage = stats.setdefault(
        "usage", {"input_tokens": 0, "output_tokens": 0, "api_calls": 0})
    stats.setdefault("upserts", 0)
    stats.setdefault("failed_batches", 0)
    stats["books_resolved"] = []

    todo = pending_books(db)
    if books is not None:
        todo = {b: raws for b, raws in todo.items() if b in books}

    known = _known_places(db, exclude=set(todo))
    in_p, out_p = PRICING_PER_MTOK.get(cfg.extraction_model, (1.0, 5.0))
    t0 = time.monotonic()
    try:
        for book in sorted(todo):
            raws = todo[book]
            book_ok = True
            for i in range(0, len(raws), BATCH_SIZE):
                batch = raws[i:i + BATCH_SIZE]
                try:
                    r = client.messages.create(
                        model=cfg.extraction_model, max_tokens=8000,
                        system=SYSTEM_PROMPT,
                        output_config={"format": {"type": "json_schema",
                                                  "schema": _OUTPUT_SCHEMA}},
                        messages=[{"role": "user", "content": json.dumps({
                            "book_number": book,
                            "known_places": [
                                {"place": k, "parent": v["parent"],
                                 "books": sorted(v["books"])}
                                for k, v in sorted(known.items())],
                            "locations": batch,
                        }, ensure_ascii=False)}])
                    usage["input_tokens"] += r.usage.input_tokens
                    usage["output_tokens"] += r.usage.output_tokens
                    usage["api_calls"] += 1
                    if r.stop_reason in ("refusal", "max_tokens"):
                        raise RuntimeError(
                            f"location call ended with {r.stop_reason}")
                    data = json.loads(
                        next(b.text for b in r.content if b.type == "text"))
                    valid = set(batch)
                    n = 0
                    for m in data.get("mappings", []):
                        if m.get("raw") not in valid:
                            continue
                        place, parent = m.get("place"), m.get("parent")
                        area = m.get("area")
                        if place:
                            entry = known.setdefault(
                                place, {"parent": parent, "books": set()})
                            entry["books"].add(book)
                            if parent and not entry["parent"]:
                                entry["parent"] = parent
                        db.execute(
                            """INSERT INTO location_map_v2
                                   (book_number, raw, place, parent, area)
                               VALUES (?,?,?,?,?)
                               ON CONFLICT(book_number, raw) DO UPDATE SET
                                   place = excluded.place,
                                   parent = excluded.parent,
                                   area = excluded.area""",
                            (book, m["raw"], place, parent,
                             area if place else None))
                        n += 1
                    db.commit()
                    stats["upserts"] += n
                    if on_batch:
                        on_batch(book, n)
                except Exception as e:
                    book_ok = False
                    stats["failed_batches"] += 1
                    log.warning("location batch failed (book %d): %s", book, e)
            if book_ok:
                db.execute(
                    "INSERT INTO enrich_state (scope, content_hash) "
                    "VALUES (?, ?) ON CONFLICT(scope) DO UPDATE SET "
                    "content_hash = excluded.content_hash",
                    (f"locmap_v2:{book}", book_hash(raws)))
                db.commit()
                stats["books_resolved"].append(book)
        # second chance for unresolved raws, now that the full known map
        # exists (Book 1 resolves before later books name anything)
        try:
            stats["backfilled"] = _backfill_unmapped(db, cfg, client,
                                                     known, usage)
        except Exception as e:
            stats["failed_batches"] += 1
            log.warning("location backfill failed: %s", e)
        # middle of the hierarchy: venues the per-book pass left parentless
        try:
            stats["parent_updates"] = _resolve_parents(db, cfg, client, usage)
        except Exception as e:
            stats["failed_batches"] += 1
            log.warning("venue-parent resolution failed: %s", e)
        # top level — last, so it sees every settlement including ones the
        # venue pass just promoted; a no-op when inputs are unchanged
        try:
            stats["region_updates"] = _resolve_regions(db, cfg, client, usage)
        except Exception as e:
            stats["failed_batches"] += 1
            log.warning("region resolution failed (settlement regions may "
                        "be missing): %s", e)
    finally:
        cost = round((usage["input_tokens"] * in_p
                      + usage["output_tokens"] * out_p) / 1e6, 4)
        stats["cost_usd"] = cost
        if usage["api_calls"]:
            log_cost(cfg, surface="locations_v2", model=cfg.extraction_model,
                     usage=usage, cost_usd=cost,
                     latency_ms=int((time.monotonic() - t0) * 1000),
                     extra={"api_calls": usage["api_calls"],
                            "rows_upserted": stats["upserts"],
                            "failed_batches": stats["failed_batches"]})
    return stats

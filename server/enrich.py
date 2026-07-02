"""Enrichment pass: distill per-chunk metadata into curated Timeline events
and per-character profiles (traits, relationship natures, per-book arcs).

Reads ONLY the already-extracted metadata (never the manuscripts), so it is
cheap. Grounding discipline: the model may summarize but cannot introduce
entities — participants are validated against the canonical character list,
locations against extracted locations, and source references are chunk IDs
we hand it (the UI shows the actual chunk text, so "quotes" are verbatim by
construction).

Incremental: work is keyed by a content hash per chapter / per character, so
re-running after a nightly ingest only touches what changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from collections import defaultdict

from src.extractor import PRICING_PER_MTOK

log = logging.getLogger(__name__)

EVENT_TYPES = ["discovery", "confrontation", "revelation", "death",
               "relationship", "journey", "decision", "loss", "victory", "other"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_number INTEGER NOT NULL,
    chapter_number INTEGER NOT NULL,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    granularity TEXT NOT NULL,
    date_line TEXT,
    summary TEXT,
    location TEXT,
    participants_json TEXT,
    knowledge_json TEXT,
    source_chunk_ids_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_pos ON events(book_number, chapter_number, position);

CREATE TABLE IF NOT EXISTS character_profiles (
    name TEXT PRIMARY KEY,
    traits_json TEXT,
    relationships_json TEXT,
    arcs_json TEXT
);

CREATE TABLE IF NOT EXISTS enrich_state (
    scope TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL
);
"""

_EVENTS_SCHEMA = {
    "type": "object",
    "properties": {"events": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "type": {"type": "string", "enum": EVENT_TYPES},
            "granularity": {"type": "string", "enum": ["major", "moderate", "minor"]},
            "summary": {"type": "string"},
            "participants": {"type": "array", "items": {"type": "string"}},
            "location": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "source_chunk_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "type", "granularity", "summary", "participants",
                     "location", "source_chunk_ids"],
        "additionalProperties": False,
    }}},
    "required": ["events"],
    "additionalProperties": False,
}

_PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "traits": {"type": "array", "items": {"type": "string"}},
        "relationships": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "nature": {"type": "string"}},
            "required": ["name", "nature"], "additionalProperties": False,
        }},
        "arcs": {"type": "array", "items": {
            "type": "object",
            "properties": {"book_number": {"type": "integer"}, "arc": {"type": "string"}},
            "required": ["book_number", "arc"], "additionalProperties": False,
        }},
    },
    "required": ["traits", "relationships", "arcs"],
    "additionalProperties": False,
}

EVENTS_PROMPT = """You are curating a story timeline from extraction notes for chapters of a fiction series. For each chapter below, consolidate its raw key-event notes into 1-4 real EVENTS (merge notes describing the same happening; skip trivia).

Rules:
- title: short and specific (5-10 words).
- participants: choose ONLY from the character names listed for that chapter — copy them exactly; never invent, expand, or normalize a name.
- location: choose from the listed locations, or null.
- source_chunk_ids: the chunk IDs (given per note) the event is drawn from.
- granularity: major = changes the course of the story; moderate = advances a plotline; minor = character/flavor beat."""

PROFILE_PROMPT = """You are summarizing one fiction character from extraction notes (their knowledge gained, emotional beats, and who they share scenes with).

Rules:
- traits: 3-6 short personality descriptors evidenced by the notes.
- relationships: for each listed co-occurring character, a 2-5 word nature ("younger brother", "girlfriend, later estranged") — ONLY the listed names, copied exactly.
- arcs: for each book number present in the notes, one 2-3 sentence arc summary.
Never invent facts not supported by the notes."""


def ensure_tables(db: sqlite3.Connection) -> None:
    db.executescript(_SCHEMA)
    db.commit()


# ── incremental hashing ─────────────────────────────────────────────────────

def _hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def _state(db, scope: str) -> str | None:
    row = db.execute("SELECT content_hash FROM enrich_state WHERE scope = ?",
                     (scope,)).fetchone()
    return row[0] if row else None


def _set_state(db, scope: str, h: str) -> None:
    db.execute("INSERT INTO enrich_state (scope, content_hash) VALUES (?, ?) "
               "ON CONFLICT(scope) DO UPDATE SET content_hash = excluded.content_hash",
               (scope, h))


# ── input assembly ──────────────────────────────────────────────────────────

def _chapter_inputs(db, canon) -> list[dict]:
    """Per-chapter payloads for event curation, with canonical names."""
    canon.ensure_built()
    chapters: dict[tuple, dict] = {}
    rows = db.execute(
        """SELECT chunk_id, book_number, chapter_number, date_line, metadata_json
           FROM chunks WHERE metadata_json IS NOT NULL
           ORDER BY book_number, chapter_number, chunk_index""").fetchall()
    for cid, book, ch, date_line, meta_json in rows:
        meta = json.loads(meta_json)
        key = (book, ch)
        entry = chapters.setdefault(key, {
            "book_number": book, "chapter_number": ch, "date_line": date_line,
            "notes": [], "characters": set(), "locations": set(), "hash_parts": []})
        for ev in meta.get("key_events", []):
            entry["notes"].append({"chunk_id": cid, "note": ev})
        entry["characters"] |= {
            c for c in (canon.resolve(n) for n in meta.get("characters_present", []))
            if c}
        entry["locations"] |= set(meta.get("locations", [])[:6])
        entry["hash_parts"].append(cid)
    out = []
    for entry in chapters.values():
        entry["characters"] = sorted(entry["characters"])
        entry["locations"] = sorted(entry["locations"])[:12]
        entry["content_hash"] = _hash(
            [entry["notes"], entry["characters"], entry["locations"]])
        del entry["hash_parts"]
        if entry["notes"]:
            out.append(entry)
    return out


def _profile_inputs(db, canon, min_chunks: int = 8) -> list[dict]:
    """Per-character payloads for the profile pass (main cast only)."""
    canon.ensure_built()
    out = []
    for e in canon.visible_entities():
        if len(e.chunk_ids) < min_chunks or e.kind == "descriptor":
            continue
        names = [e.name, *e.aliases]
        knowledge = db.execute(
            f"""SELECT c.book_number, k.learns FROM character_knowledge k
                JOIN chunks c ON c.chunk_id = k.chunk_id
                WHERE {' OR '.join('k.character LIKE ?' for _ in names)}
                ORDER BY c.book_number, c.chapter_number LIMIT 220""",
            [f"%{n}%" for n in names]).fetchall()
        beats = db.execute(
            f"""SELECT c.book_number, c.metadata_json FROM chunks c
                JOIN characters ch ON ch.chunk_id = c.chunk_id
                WHERE ch.name IN ({','.join('?' for _ in names)})
                ORDER BY c.book_number, c.chapter_number LIMIT 400""",
            names).fetchall()
        beat_lines = []
        for book, meta_json in beats:
            if meta_json:
                for b in json.loads(meta_json).get("emotional_beats", []):
                    if any(n.split()[0] in b for n in names):
                        beat_lines.append(f"[Book {book}] {b}")
        co = [n for n, _ in canon.co_occurrence(e.name)[:8]]
        payload = {
            "name": e.name,
            "knowledge": [f"[Book {b}] {v}" for b, v in knowledge],
            "beats": beat_lines[:200],
            "co_occurring": co,
        }
        payload["content_hash"] = _hash([payload["knowledge"][:50],
                                         payload["beats"][:50], co])
        out.append(payload)
    return out


# ── cost preview ────────────────────────────────────────────────────────────

def preview(db, cfg, canon) -> dict:
    ensure_tables(db)
    chapters = [c for c in _chapter_inputs(db, canon)
                if _state(db, f"events:{c['book_number']}.{c['chapter_number']}")
                != c["content_hash"]]
    profiles = [p for p in _profile_inputs(db, canon)
                if _state(db, f"profile:{p['name']}") != p["content_hash"]]
    in_tok = sum(len(json.dumps(c["notes"])) // 3 + 400 for c in chapters) \
        + sum((len(p["knowledge"]) + len(p["beats"])) * 20 + 500 for p in profiles)
    out_tok = len(chapters) * 350 + len(profiles) * 500
    in_p, out_p = PRICING_PER_MTOK.get(cfg.extraction_model, (1.0, 5.0))
    return {
        "chapters_to_process": len(chapters),
        "profiles_to_process": len(profiles),
        "estimated_cost_usd": round((in_tok * in_p + out_tok * out_p) / 1e6, 3),
        "model": cfg.extraction_model,
    }


# ── run ─────────────────────────────────────────────────────────────────────

class EnrichmentRunner:
    """Background enrichment with observable progress."""

    def __init__(self):
        self.status = {"state": "idle", "done": 0, "total": 0, "cost_usd": 0.0,
                       "error": None}
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, db_path, cfg, canon_factory) -> bool:
        if self.running:
            return False
        self._thread = threading.Thread(
            target=self._run, args=(db_path, cfg, canon_factory), daemon=True)
        self._thread.start()
        return True

    def _run(self, db_path, cfg, canon_factory) -> None:
        import anthropic
        try:
            db = sqlite3.connect(db_path)  # thread-local connection
            canon = canon_factory(db)
            ensure_tables(db)
            client = anthropic.Anthropic(api_key=cfg.anthropic_api_key or None,
                                         max_retries=4)
            in_p, out_p = PRICING_PER_MTOK.get(cfg.extraction_model, (1.0, 5.0))

            chapters = [c for c in _chapter_inputs(db, canon)
                        if _state(db, f"events:{c['book_number']}.{c['chapter_number']}")
                        != c["content_hash"]]
            profiles = [p for p in _profile_inputs(db, canon)
                        if _state(db, f"profile:{p['name']}") != p["content_hash"]]
            self.status.update(state="running", done=0,
                               total=len(chapters) + len(profiles),
                               cost_usd=0.0, error=None)

            def call(system, user, schema):
                r = client.messages.create(
                    model=cfg.extraction_model, max_tokens=8000, system=system,
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                    messages=[{"role": "user", "content": user}])
                self.status["cost_usd"] = round(
                    self.status["cost_usd"]
                    + (r.usage.input_tokens * in_p + r.usage.output_tokens * out_p) / 1e6, 4)
                if r.stop_reason in ("refusal", "max_tokens"):
                    raise RuntimeError(f"enrichment call ended with {r.stop_reason}")
                return json.loads(next(b.text for b in r.content if b.type == "text"))

            # events — one small call per chapter (log-and-continue on failure)
            for c in chapters:
                try:
                    data = call(EVENTS_PROMPT, json.dumps(
                        {k: v for k, v in c.items() if k != "content_hash"},
                        ensure_ascii=False), _EVENTS_SCHEMA)
                    self._store_events(db, c, data.get("events", []))
                    _set_state(db, f"events:{c['book_number']}.{c['chapter_number']}",
                               c["content_hash"])
                    db.commit()
                except Exception as e:
                    log.warning("event enrichment failed for book %s ch %s: %s",
                                c["book_number"], c["chapter_number"], e)
                self.status["done"] += 1

            # profiles — one call each
            for p in profiles:
                try:
                    user = json.dumps({k: v for k, v in p.items()
                                       if k != "content_hash"}, ensure_ascii=False)
                    data = call(PROFILE_PROMPT, user, _PROFILE_SCHEMA)
                    self._store_profile(db, p, data)
                    _set_state(db, f"profile:{p['name']}", p["content_hash"])
                    db.commit()
                except Exception as e:
                    log.warning("profile enrichment failed for %s: %s", p["name"], e)
                self.status["done"] += 1

            self.status["state"] = "done"
        except Exception as e:
            log.exception("enrichment run failed")
            self.status.update(state="error", error=str(e))

    @staticmethod
    def _store_events(db, chapter: dict, events: list[dict]) -> None:
        book, ch = chapter["book_number"], chapter["chapter_number"]
        valid_chars = set(chapter["characters"])
        valid_chunks = {n["chunk_id"] for n in chapter["notes"]}
        valid_locs = set(chapter["locations"])
        db.execute("DELETE FROM events WHERE book_number = ? AND chapter_number = ?",
                   (book, ch))
        for pos, ev in enumerate(events):
            participants = [p for p in ev.get("participants", []) if p in valid_chars]
            sources = [s for s in ev.get("source_chunk_ids", []) if s in valid_chunks]
            location = ev.get("location") if ev.get("location") in valid_locs else None
            knowledge = []  # knowledge impacts come from the chunk metadata
            for cid in sources:
                row = db.execute("SELECT metadata_json FROM chunks WHERE chunk_id = ?",
                                 (cid,)).fetchone()
                if row and row[0]:
                    for who, facts in json.loads(row[0]).get(
                            "character_knowledge_updates", {}).items():
                        knowledge.extend({"character": who, "learns": f} for f in facts)
            db.execute(
                """INSERT INTO events (book_number, chapter_number, position, title,
                       type, granularity, date_line, summary, location,
                       participants_json, knowledge_json, source_chunk_ids_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (book, ch, pos, ev["title"], ev["type"], ev["granularity"],
                 chapter.get("date_line"), ev.get("summary"), location,
                 json.dumps(participants, ensure_ascii=False),
                 json.dumps(knowledge[:12], ensure_ascii=False),
                 json.dumps(sources)))

    @staticmethod
    def _store_profile(db, payload: dict, data: dict) -> None:
        valid = set(payload["co_occurring"])
        relationships = [r for r in data.get("relationships", [])
                         if r.get("name") in valid]
        arcs = {str(a["book_number"]): a["arc"] for a in data.get("arcs", [])}
        db.execute(
            """INSERT INTO character_profiles (name, traits_json, relationships_json, arcs_json)
               VALUES (?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET traits_json = excluded.traits_json,
                   relationships_json = excluded.relationships_json,
                   arcs_json = excluded.arcs_json""",
            (payload["name"], json.dumps(data.get("traits", []), ensure_ascii=False),
             json.dumps(relationships, ensure_ascii=False),
             json.dumps(arcs, ensure_ascii=False)))


runner = EnrichmentRunner()

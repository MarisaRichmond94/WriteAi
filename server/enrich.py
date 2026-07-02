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
import re
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
        "arcs": {"type": "array", "items": {
            "type": "object",
            "properties": {"book_number": {"type": "integer"}, "arc": {"type": "string"}},
            "required": ["book_number", "arc"], "additionalProperties": False,
        }},
    },
    "required": ["traits", "arcs"],
    "additionalProperties": False,
}

# Relationship natures are handled by a SEPARATE evidence-based pass: the model
# only ever sees verbatim prose snippets and must quote its evidence, which we
# verify mechanically. No evidence -> null nature. This prevents invented
# family structure ("younger brother", "cousin") that plagued nature labels
# derived from distilled notes.
_REL_SCHEMA = {
    "type": "object",
    "properties": {"relationships": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "nature": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "evidence": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["name", "nature", "evidence"],
        "additionalProperties": False,
    }}},
    "required": ["relationships"],
    "additionalProperties": False,
}

REL_PROMPT = """You are identifying how characters in a novel are related, using ONLY the prose excerpts provided. Each excerpt is labeled with its narrator ("I" in the excerpt is that narrator).

For each listed character, state what that character IS to the main_character (e.g. "older brother", "best friend", "girlfriend", "father", "coach").

DIRECTION RULES — read carefully, this is where mistakes happen:
- nature answers: "who is <character> to <main_character>?"
- Worked example: main_character is Alex; the excerpt is "[narrator: Sam] I have two older brothers—Alex and Ben." Here SAM says ALEX is one of Sam's older brothers. So for main_character Alex and character Sam, Sam is Alex's YOUNGER sibling — nature: "younger brother". (If instead main_character were Sam and character Alex, nature would be "older brother".)
- Always work out who "I"/"my" refers to via the narrator label before assigning older/younger.
- Directional details (older/younger) may only be included if the text states them.

OTHER RULES:
- The excerpts must EXPLICITLY establish the relationship.
- Copy the single most decisive excerpt VERBATIM into evidence (the exact substring, unmodified).
- If the excerpts do not explicitly establish a relationship for a character, return nature=null and evidence=null. Never guess from tone or behavior."""

_REL_KEYWORDS = (
    "brother", "sister", "sibling", "father", "dad", "mother", "mom", "mum",
    "cousin", "uncle", "aunt", "grandpa", "grandfather", "grandma",
    "grandmother", "son", "daughter", "husband", "wife", "fiancé", "fiancée",
    "boyfriend", "girlfriend", "best friend", "friend", "married", "dating",
    "ex-", "stepbrother", "stepsister", "half-brother", "coach", "teacher",
    "counselor", "principal", "teammate", "mentor", "boss", "partner",
)

_SENT_SPLIT = re.compile(r"(?<=[.!?”\"])\s+")

EVENTS_PROMPT = """You are curating a story timeline from extraction notes for chapters of a fiction series. For each chapter below, consolidate its raw key-event notes into 1-4 real EVENTS (merge notes describing the same happening; skip trivia).

Rules:
- title: short and specific (5-10 words).
- participants: choose ONLY from the character names listed for that chapter — copy them exactly; never invent, expand, or normalize a name.
- location: choose from the listed locations, or null.
- source_chunk_ids: the chunk IDs (given per note) the event is drawn from.
- granularity: major = changes the course of the story; moderate = advances a plotline; minor = character/flavor beat."""

PROFILE_PROMPT = """You are summarizing one fiction character from extraction notes (their knowledge gained and emotional beats).

Rules:
- traits: 3-6 short personality descriptors evidenced by the notes.
- arcs: for each book number present in the notes, one 2-3 sentence arc summary.
Never invent facts not supported by the notes. Do NOT describe how characters are related to each other — that is handled elsewhere."""


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


def _entity_names(canon, name: str) -> list[str]:
    e = canon.entities.get(name)
    return [name, *(e.aliases if e else [])]


def _mention_tokens(names: list[str]) -> set[str]:
    """Tokens that count as 'mentioning' a character in a sentence."""
    tokens = set()
    for n in names:
        tokens.add(n)
        first = n.split()[0]
        if len(first) >= 3:
            tokens.add(first)
    return tokens


def relationship_evidence(db, canon, name: str, others: list[str],
                          max_per_pair: int = 10) -> dict[str, list[str]]:
    """Mine verbatim prose sentences that could establish how `name` relates
    to each of `others`: sentences from shared scenes that mention the other
    character AND contain a relationship keyword. Purely mechanical."""
    canon.ensure_built()
    me = canon.entities.get(name)
    if me is None:
        return {}
    pov_by_chunk = dict(db.execute("SELECT chunk_id, pov_character FROM chunks"))
    evidence: dict[str, list[str]] = {o: [] for o in others}
    my_tokens = _mention_tokens(_entity_names(canon, name))
    other_tokens = {o: _mention_tokens(_entity_names(canon, o)) for o in others}
    # search chunks where EITHER character is tagged — extraction sometimes
    # misses a participant that the prose still names (e.g. "Austin's lying")
    search_ids = set(me.chunk_ids)
    for o in others:
        oe = canon.entities.get(o)
        if oe:
            search_ids |= oe.chunk_ids

    # Definitional/directional phrases outrank generic keyword hits, so the
    # decisive sentence ("my older brother, Noah") always makes the cut.
    strong = ("older brother", "oldest brother", "big brother", "little brother",
              "younger brother", "youngest", "older sister", "little sister",
              "best friend", "stepbrother", "stepsister", "my cousin",
              "girlfriend", "boyfriend", "my father", "my mother", "my dad",
              "my mom", "my uncle", "my aunt", "my grandpa", "my grandma")
    candidates: dict[str, list[tuple[int, int, str]]] = {o: [] for o in others}

    for order, cid in enumerate(sorted(search_ids)):
        present = canon.chunk_entities.get(cid, set())
        row = db.execute("SELECT text FROM chunks WHERE chunk_id = ?", (cid,)).fetchone()
        if not row:
            continue
        narrator = pov_by_chunk.get(cid) or "unknown"
        i_am_narrator = narrator and narrator.split()[0] in {t.split()[0] for t in my_tokens}
        sentences = _SENT_SPLIT.split(row[0])
        for i, s in enumerate(sentences):
            low = s.lower()
            if not any(k in low for k in _REL_KEYWORDS):
                continue
            prev = sentences[i - 1] if i > 0 else ""
            prev2 = sentences[i - 2] if i > 1 else ""
            pair_text = f"{prev} {s}" if prev else s
            match_window = f"{prev2} {pair_text}"
            score = 2 if any(k in low for k in strong) else 1
            # the main character must be involved: tagged in the chunk,
            # named in the window, or the narrator of the scene
            me_involved = (name in present or i_am_narrator
                           or any(t in match_window for t in my_tokens))
            if not me_involved:
                continue
            for o in others:
                # dialogue often names the character a sentence or two before
                # the descriptor ("Austin's lying." "…he's your best friend")
                if any(t in match_window for t in other_tokens[o]):
                    snippet = f"[narrator: {narrator}] {pair_text}".strip()
                    candidates[o].append((-score, order, snippet[:420]))

    for o in others:
        ranked = sorted(candidates[o])[:max_per_pair]
        evidence[o] = [snippet for _, _, snippet in ranked]
    return evidence


def _profile_inputs(db, canon, min_chunks: int = 8) -> list[dict]:
    """Per-character payloads for the profile pass (main cast only)."""
    canon.ensure_built()
    out = []
    for e in canon.visible_entities():
        if len(e.chunk_ids) < min_chunks or e.kind != "character":
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
        payload["content_hash"] = _hash(["v2", payload["knowledge"][:50],
                                         payload["beats"][:50], co])
        out.append(payload)
    return out


def _rel_inputs(db, canon) -> list[dict]:
    """Per-character evidence bundles for the relationship-nature pass."""
    out = []
    for p in _profile_inputs(db, canon):
        others = p["co_occurring"]
        if not others:
            continue
        evidence = relationship_evidence(db, canon, p["name"], others)
        out.append({
            "name": p["name"],
            "others": others,
            "evidence": evidence,
            "content_hash": _hash(["rel-v4", evidence]),
        })
    return out


# ── cost preview ────────────────────────────────────────────────────────────

def preview(db, cfg, canon) -> dict:
    ensure_tables(db)
    chapters = [c for c in _chapter_inputs(db, canon)
                if _state(db, f"events:{c['book_number']}.{c['chapter_number']}")
                != c["content_hash"]]
    profiles = [p for p in _profile_inputs(db, canon)
                if _state(db, f"profile:{p['name']}") != p["content_hash"]]
    rels = [r for r in _rel_inputs(db, canon)
            if _state(db, f"rels:{r['name']}") != r["content_hash"]]
    in_tok = sum(len(json.dumps(c["notes"])) // 3 + 400 for c in chapters) \
        + sum((len(p["knowledge"]) + len(p["beats"])) * 20 + 500 for p in profiles) \
        + sum(len(json.dumps(r["evidence"])) // 3 + 400 for r in rels)
    out_tok = len(chapters) * 350 + len(profiles) * 500 + len(rels) * 250
    in_p, out_p = PRICING_PER_MTOK.get(cfg.extraction_model, (1.0, 5.0))
    return {
        "chapters_to_process": len(chapters),
        "profiles_to_process": len(profiles),
        "relationships_to_process": len(rels),
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
            rels = [r for r in _rel_inputs(db, canon)
                    if _state(db, f"rels:{r['name']}") != r["content_hash"]]
            self.status.update(state="running", done=0,
                               total=len(chapters) + len(profiles) + len(rels),
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

            # profiles (traits + arcs) — one call each
            for p in profiles:
                try:
                    user = json.dumps({k: v for k, v in p.items()
                                       if k not in ("content_hash", "co_occurring")},
                                      ensure_ascii=False)
                    data = call(PROFILE_PROMPT, user, _PROFILE_SCHEMA)
                    self._store_profile(db, p, data)
                    _set_state(db, f"profile:{p['name']}", p["content_hash"])
                    db.commit()
                except Exception as e:
                    log.warning("profile enrichment failed for %s: %s", p["name"], e)
                self.status["done"] += 1

            # relationship natures — evidence-based, quote-verified
            strong_hint = ("older brother", "oldest brother", "big brother",
                           "little brother", "best friend", "girlfriend",
                           "boyfriend", "my cousin", "stepbrother")
            for r in rels:
                try:
                    user = json.dumps({
                        "main_character": r["name"],
                        "characters": r["others"],
                        "excerpts": r["evidence"],
                    }, ensure_ascii=False)
                    data = call(REL_PROMPT, user, _REL_SCHEMA)
                    by_name = {x.get("name"): x for x in data.get("relationships", [])}
                    # focused retry: pairs the model left null even though a
                    # decisive phrase is sitting in the snippets
                    for o in r["others"]:
                        answered = by_name.get(o, {}).get("nature")
                        snippets = r["evidence"].get(o, [])
                        if answered or not any(
                                h in s.lower() for s in snippets for h in strong_hint):
                            continue
                        retry = call(REL_PROMPT, json.dumps({
                            "main_character": r["name"],
                            "characters": [o],
                            "excerpts": {o: snippets},
                        }, ensure_ascii=False), _REL_SCHEMA)
                        for x in retry.get("relationships", []):
                            if x.get("name") == o and x.get("nature"):
                                by_name[o] = x
                    data = {"relationships": list(by_name.values())}
                    self._store_relationships(db, r, data)
                    _set_state(db, f"rels:{r['name']}", r["content_hash"])
                    db.commit()
                except Exception as e:
                    log.warning("relationship enrichment failed for %s: %s", r["name"], e)
                self.status["done"] += 1

            self._reconcile_directions(db)
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
        """Update traits + arcs, leaving relationships to the evidence pass."""
        arcs = {str(a["book_number"]): a["arc"] for a in data.get("arcs", [])}
        db.execute(
            """INSERT INTO character_profiles (name, traits_json, relationships_json, arcs_json)
               VALUES (?, ?, COALESCE((SELECT relationships_json FROM character_profiles
                                       WHERE name = ?), '[]'), ?)
               ON CONFLICT(name) DO UPDATE SET traits_json = excluded.traits_json,
                   arcs_json = excluded.arcs_json""",
            (payload["name"], json.dumps(data.get("traits", []), ensure_ascii=False),
             payload["name"], json.dumps(arcs, ensure_ascii=False)))

    @staticmethod
    def _reconcile_directions(db) -> None:
        """Mechanical sanity check: two characters cannot BOTH be each
        other's 'older brother' (or both 'younger'). When the model produced
        a contradictory mutual pair, null both sides — an honest blank beats
        a coin flip."""
        profiles = {name: json.loads(rj or "[]") for name, rj in db.execute(
            "SELECT name, relationships_json FROM character_profiles")}

        def direction(nature: str | None) -> str | None:
            if not nature:
                return None
            low = nature.lower()
            if "older" in low or "big " in low or "oldest" in low:
                return "older"
            if "younger" in low or "little " in low or "youngest" in low:
                return "younger"
            return None

        changed = set()
        for a, rels in profiles.items():
            for r in rels:
                b = r["name"]
                d_ab = direction(r.get("nature"))
                if d_ab is None or b not in profiles:
                    continue
                back = next((x for x in profiles[b] if x["name"] == a), None)
                if back is None:
                    continue
                d_ba = direction(back.get("nature"))
                if d_ba is not None and d_ab == d_ba:
                    log.warning("contradictory sibling direction %s<->%s "
                                "(%r / %r) — nulling both",
                                a, b, r.get("nature"), back.get("nature"))
                    r["nature"] = r["evidence"] = None
                    back["nature"] = back["evidence"] = None
                    changed |= {a, b}
        for name in changed:
            db.execute("UPDATE character_profiles SET relationships_json = ? "
                       "WHERE name = ?",
                       (json.dumps(profiles[name], ensure_ascii=False), name))
        db.commit()

    @staticmethod
    def _store_relationships(db, payload: dict, data: dict) -> None:
        """Store natures ONLY when the model's quoted evidence verifies
        against the snippets we supplied. Everything else is null — an honest
        blank beats an invented relationship. Matching normalizes quote
        characters and whitespace (models straighten curly quotes when
        copying) but still requires a real substring match."""

        def norm(s: str) -> str:
            for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                         ("—", "-"), ("…", "...")):
                s = s.replace(a, b)
            return re.sub(r"\s+", " ", s).strip().lower()

        valid = set(payload["others"])
        verified = []
        for r in data.get("relationships", []):
            name = r.get("name")
            if name not in valid:
                continue
            nature, evidence = r.get("nature"), r.get("evidence")
            snippets = payload["evidence"].get(name, [])
            ok = bool(nature and evidence
                      and any(norm(evidence) in norm(s) for s in snippets))
            if nature and not ok:
                log.info("rejected unverified nature %r for %s -> %s",
                         nature, payload["name"], name)
            verified.append({
                "name": name,
                "nature": nature if ok else None,
                "evidence": evidence if ok else None,
            })
        db.execute(
            """INSERT INTO character_profiles (name, traits_json, relationships_json, arcs_json)
               VALUES (?, COALESCE((SELECT traits_json FROM character_profiles
                                    WHERE name = ?), '[]'), ?,
                       COALESCE((SELECT arcs_json FROM character_profiles
                                 WHERE name = ?), '{}'))
               ON CONFLICT(name) DO UPDATE SET relationships_json = excluded.relationships_json""",
            (payload["name"], payload["name"],
             json.dumps(verified, ensure_ascii=False), payload["name"]))


runner = EnrichmentRunner()

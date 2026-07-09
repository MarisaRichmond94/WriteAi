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
import time
from collections import defaultdict

from src.costlog import log_cost
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

CREATE TABLE IF NOT EXISTS chapter_summaries (
    book_number INTEGER NOT NULL,
    chapter_number INTEGER NOT NULL,
    summary TEXT NOT NULL,
    PRIMARY KEY (book_number, chapter_number)
);

CREATE TABLE IF NOT EXISTS location_map (
    raw TEXT PRIMARY KEY,
    place TEXT,
    parent TEXT
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
            "quote": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["title", "type", "granularity", "summary", "participants",
                     "location", "source_chunk_ids", "quote"],
        "additionalProperties": False,
    }},
    "chapter_summary": {"type": "string"}},
    "required": ["events", "chapter_summary"],
    "additionalProperties": False,
}

_LOC_SCHEMA = {
    "type": "object",
    "properties": {"mappings": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "raw": {"type": "string"},
            "place": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "parent": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["raw", "place", "parent"],
        "additionalProperties": False,
    }}},
    "required": ["mappings"],
    "additionalProperties": False,
}

LOC_PROMPT = """You are normalizing location strings extracted from a fiction series into a clean two-level gazetteer.

For each raw string, return:
- place: the canonical location at one of exactly two granularities —
  a SETTLEMENT (town, city, e.g. "Los Angeles") or a VENUE (a specific home,
  school, business, or landmark, e.g. "Emma's house", "Crestwood High School").
  Sub-areas collapse to their venue: "Emma's house - porch" -> "Emma's house";
  "gym at Crestwood High" -> "Crestwood High School".
- parent: the settlement the venue is in, when the strings make it clear;
  null otherwise. A settlement's own parent is null.
- place = null for NON-places and unusable fragments: phone/video calls,
  events described as places, vehicles and driving, roads and highways,
  street addresses with no named venue, and generic unanchored rooms
  ("a basement room", "a dark alleyway"). A missing location is better
  than a bad one.

CONSISTENCY: known_places lists canonical names already established (with
their parents). When a raw string refers to one of them, copy that name
EXACTLY. Never invent multiple spellings of the same place."""

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

EVENTS_PROMPT = """You are curating a story timeline from a chapter of a fiction series. You get the chapter PROSE plus raw key-event notes. Consolidate the notes into 1-4 real EVENTS (merge notes describing the same happening; skip trivia), and write one chapter summary.

Event rules:
- title: short and specific (5-10 words).
- participants: choose ONLY from the character names listed for that chapter — copy them exactly; never invent, expand, or normalize a name.
- location: choose from the listed locations, or null.
- source_chunk_ids: the chunk IDs (given per note) the event is drawn from.
- granularity: major = changes the course of the story; moderate = advances a plotline; minor = character/flavor beat.
- quote: the single most dramatic or representative line of the PROSE for this event — the line a reader would underline. Copy it EXACTLY, character for character, from the prose (1-2 sentences, under 300 characters). If no line stands out, null. Never paraphrase.

chapter_summary: 3-5 sentences of flowing prose (present tense) summarizing the chapter for the author's own reference: what happens, what shifts emotionally, what it sets up. No headers, no bullets, no editorializing about craft."""

PROFILE_PROMPT = """You are summarizing one fiction character from extraction notes (their knowledge gained and emotional beats).

Rules:
- traits: 3-6 short personality descriptors evidenced by the notes.
- arcs: for each book number present in the notes, one 2-3 sentence arc summary.
Never invent facts not supported by the notes. Do NOT describe how characters are related to each other — that is handled elsewhere."""


def ensure_tables(db: sqlite3.Connection) -> None:
    db.executescript(_SCHEMA)
    try:  # added after the table shipped
        db.execute("ALTER TABLE events ADD COLUMN quote TEXT")
    except sqlite3.OperationalError:
        pass
    db.commit()


def gc_orphans(db: sqlite3.Connection) -> int:
    """Remove enrichment rows for (book, chapter) pairs no longer present in
    chunks. Enrichment only ever rewrites chapters that currently exist, so
    after a renumbering or a shrunk book the vanished chapter numbers would
    keep serving their old events/summaries forever — the same scenes under
    stale labels, which reviews then present as duplicate story material.
    Returns the number of rows deleted. Safe on a DB with no chunks table yet."""
    ensure_tables(db)
    total = 0
    try:
        for table in ("events", "chapter_summaries"):
            total += db.execute(
                f"""DELETE FROM {table} WHERE NOT EXISTS (
                        SELECT 1 FROM chunks k
                        WHERE k.book_number = {table}.book_number
                          AND k.chapter_number = {table}.chapter_number)"""
            ).rowcount
        total += db.execute(
            """DELETE FROM enrich_state WHERE scope LIKE 'events:%'
               AND scope NOT IN (SELECT 'events:' || book_number || '.'
                                        || chapter_number FROM chunks)"""
        ).rowcount
    except sqlite3.OperationalError:  # ingest has never run — nothing to GC
        db.rollback()
        return 0
    if total:
        db.commit()
    return total


def norm_quote(s: str) -> str:
    """Normalize for verbatim-quote matching: models straighten curly quotes
    and collapse whitespace when copying, but the words must match exactly."""
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
                 ("\u2014", "-"), ("\u2026", "...")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


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
    texts = dict(db.execute("SELECT chunk_id, text FROM chunks"))
    povs = dict(db.execute("SELECT chunk_id, pov_character FROM chunks"))
    for cid, book, ch, date_line, meta_json in rows:
        meta = json.loads(meta_json)
        key = (book, ch)
        entry = chapters.setdefault(key, {
            "book_number": book, "chapter_number": ch, "date_line": date_line,
            "pov": povs.get(cid), "prose": [],
            "notes": [], "characters": set(), "locations": set(), "hash_parts": []})
        entry["prose"].append({"chunk_id": cid, "text": texts.get(cid, "")})
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
            ["ev2", entry["notes"], entry["characters"], entry["locations"],
             hashlib.sha256("".join(t["text"] for t in entry["prose"])
                            .encode()).hexdigest()])
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


def _cap_per_book(rows: list[tuple], budget: int) -> list[tuple]:
    """Spread a row budget evenly across books. A flat LIMIT ordered by book
    let early books exhaust the budget, so main characters lost their later
    books entirely — and with them their arcs for those books."""
    by_book: dict[int, list] = {}
    for row in rows:
        by_book.setdefault(row[0], []).append(row)
    per = max(1, budget // max(1, len(by_book)))
    return [r for b in sorted(by_book) for r in by_book[b][:per]]


def _loc_inputs(db) -> tuple[list[list[str]], str]:
    """Distinct raw location strings in batches, plus a content hash."""
    raws = [r[0] for r in db.execute(
        "SELECT DISTINCT name FROM locations ORDER BY name")]
    batches = [raws[i:i + 120] for i in range(0, len(raws), 120)]
    return batches, _hash(["locmap-v1", raws])


def _loc_pending(db, cfg) -> tuple[list[list[str]], str | None]:
    """Location batches still to resolve, honoring ENABLE_LOCATION_V2.

    v2 (flag on) returns per-book batches — book-scoped state lives inside
    src.location_resolve, so the hash is None. v1 returns the series-wide
    batches plus the state hash that skips the whole pass when unchanged."""
    if getattr(cfg, "enable_location_v2", False):
        from src.location_resolve import BATCH_SIZE, ensure_table, pending_books
        ensure_table(db)
        return [raws[i:i + BATCH_SIZE]
                for _b, raws in sorted(pending_books(db).items())
                for i in range(0, len(raws), BATCH_SIZE)], None
    batches, h = _loc_inputs(db)
    if _state(db, "locmap") == h:
        batches = []
    return batches, h


def _profile_inputs(db, canon, min_chunks: int = 8) -> list[dict]:
    """Per-character payloads for the profile pass (main cast only)."""
    canon.ensure_built()
    out = []
    for e in canon.visible_entities():
        if len(e.chunk_ids) < min_chunks or e.kind != "character":
            continue
        names = [e.name, *e.aliases]
        knowledge = _cap_per_book(db.execute(
            f"""SELECT c.book_number, k.learns FROM character_knowledge k
                JOIN chunks c ON c.chunk_id = k.chunk_id
                WHERE {' OR '.join('k.character LIKE ?' for _ in names)}
                ORDER BY c.book_number, c.chapter_number""",
            [f"%{n}%" for n in names]).fetchall(), 220)
        beats = _cap_per_book(db.execute(
            f"""SELECT c.book_number, c.metadata_json FROM chunks c
                JOIN characters ch ON ch.chunk_id = c.chunk_id
                WHERE ch.name IN ({','.join('?' for _ in names)})
                ORDER BY c.book_number, c.chapter_number""",
            names).fetchall(), 400)
        beat_rows = []
        for book, meta_json in beats:
            if meta_json:
                for b in json.loads(meta_json).get("emotional_beats", []):
                    if any(n.split()[0] in b for n in names):
                        beat_rows.append((book, f"[Book {book}] {b}"))
        beat_lines = [line for _b, line in _cap_per_book(beat_rows, 200)]
        co = [n for n, _ in canon.co_occurrence(e.name)[:8]]
        payload = {
            "name": e.name,
            "knowledge": [f"[Book {b}] {v}" for b, v in knowledge],
            "beats": beat_lines,
            "co_occurring": co,
        }
        payload["content_hash"] = _hash(["v2", payload["knowledge"][:50],
                                         payload["beats"][:50], co])
        out.append(payload)
    return out


def _rel_inputs(db, canon) -> list[dict]:
    """Per-character evidence bundles for the relationship-nature pass.

    Candidates go deeper than the profile payload's top-8 co-occurring:
    ground-truth checks showed real relationships (user-curated ones) falling
    outside the top 8, so this pass considers the top 16."""
    out = []
    for p in _profile_inputs(db, canon):
        others = [n for n, _ in canon.co_occurrence(p["name"])[:16]]
        if not others:
            continue
        evidence = relationship_evidence(db, canon, p["name"], others)
        out.append({
            "name": p["name"],
            "others": others,
            "evidence": evidence,
            "content_hash": _hash(["rel-v7", evidence]),
        })
    return out


_STRONG_HINTS = ("older brother", "oldest brother", "big brother",
                 "little brother", "best friend", "girlfriend",
                 "boyfriend", "my cousin", "stepbrother")

_REL_RETRY_NOTE = (
    "\n\nRETRY: your previous evidence for this character was rejected "
    "because it was not an exact substring of any excerpt. Pick the single "
    "most decisive excerpt and copy the evidence from it character for "
    "character — no ellipses, no merging, no rephrasing.")


def _evidence_verifies(evidence: str | None, snippets: list[str]) -> bool:
    return bool(evidence) and any(
        norm_quote(evidence) in norm_quote(s) for s in snippets)


def label_relationships(call, bundle: dict) -> dict:
    """Run one evidence bundle through the model: the main call, then one
    focused retry per pair that either (a) came back null despite a decisive
    phrase sitting in the snippets, or (b) came back with a nature whose
    evidence is not a verbatim substring of any snippet — _store_relationships
    would null it, and a correct nature with a sloppy quote is the most
    common recoverable failure. `call` is (system, user, schema) -> dict."""
    data = call(REL_PROMPT, json.dumps({
        "main_character": bundle["name"],
        "characters": bundle["others"],
        "excerpts": bundle["evidence"],
    }, ensure_ascii=False), _REL_SCHEMA)
    by_name = {x.get("name"): x for x in data.get("relationships", [])}
    for o in bundle["others"]:
        x = by_name.get(o) or {}
        snippets = bundle["evidence"].get(o, [])
        bad_quote = bool(x.get("nature")) and not _evidence_verifies(
            x.get("evidence"), snippets)
        missed = not x.get("nature") and any(
            h in s.lower() for s in snippets for h in _STRONG_HINTS)
        if not (bad_quote or missed):
            continue
        retry = call(REL_PROMPT + (_REL_RETRY_NOTE if bad_quote else ""),
                     json.dumps({
                         "main_character": bundle["name"],
                         "characters": [o],
                         "excerpts": {o: snippets},
                     }, ensure_ascii=False), _REL_SCHEMA)
        for rx in retry.get("relationships", []):
            if (rx.get("name") == o and rx.get("nature")
                    and _evidence_verifies(rx.get("evidence"), snippets)):
                by_name[o] = rx
    return {"relationships": list(by_name.values())}


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
    loc_batches, _loc_hash = _loc_pending(db, cfg)
    rel_in = sum(len(json.dumps(r["evidence"])) // 3 + 400 for r in rels)
    rel_out = len(rels) * 250
    in_tok = sum(len(json.dumps(b)) // 3 + 600 for b in loc_batches) + sum(len(json.dumps(c["notes"])) // 3
                 + sum(len(t["text"]) for t in c["prose"]) // 3 + 400
                 for c in chapters) \
        + sum((len(p["knowledge"]) + len(p["beats"])) * 20 + 500 for p in profiles)
    out_tok = (len(chapters) * 550 + len(profiles) * 500
               + sum(len(b) * 25 for b in loc_batches))
    in_p, out_p = PRICING_PER_MTOK.get(cfg.extraction_model, (1.0, 5.0))
    rel_model = cfg.enrich_rel_model or cfg.extraction_model
    rel_in_p, rel_out_p = PRICING_PER_MTOK.get(rel_model, (in_p, out_p))
    return {
        "chapters_to_process": len(chapters),
        "profiles_to_process": len(profiles),
        "relationships_to_process": len(rels),
        "location_batches_to_process": len(loc_batches),
        "estimated_cost_usd": round((in_tok * in_p + out_tok * out_p
                                     + rel_in * rel_in_p + rel_out * rel_out_p) / 1e6, 3),
        "model": cfg.extraction_model,
        "rel_model": rel_model,
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
        run_usage = {"input_tokens": 0, "output_tokens": 0, "api_calls": 0}
        t0 = time.monotonic()
        try:
            db = sqlite3.connect(db_path)  # thread-local connection
            canon = canon_factory(db)
            ensure_tables(db)
            removed = gc_orphans(db)
            if removed:
                log.info("enrichment GC: removed %d stale row(s) for chapters "
                         "no longer in the index", removed)
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
            loc_batches, loc_hash = _loc_pending(db, cfg)
            # story-order chronology (ENABLE_STORY_ORDER): one task per book
            # whose chapters changed this run. Flag off -> empty -> the run
            # is exactly what it was before this phase existed.
            chrono_books: list[int] = (
                sorted({c["book_number"] for c in chapters})
                if getattr(cfg, "enable_story_order", False) else [])
            self.status.update(state="running", done=0,
                               total=(len(chapters) + len(profiles) + len(rels)
                                      + len(loc_batches) + len(chrono_books)),
                               cost_usd=0.0, error=None)

            def call(system, user, schema, model=None):
                m = model or cfg.extraction_model
                m_in, m_out = PRICING_PER_MTOK.get(m, (in_p, out_p))
                r = client.messages.create(
                    model=m, max_tokens=8000, system=system,
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                    messages=[{"role": "user", "content": user}])
                self.status["cost_usd"] = round(
                    self.status["cost_usd"]
                    + (r.usage.input_tokens * m_in + r.usage.output_tokens * m_out) / 1e6, 4)
                run_usage["input_tokens"] += r.usage.input_tokens
                run_usage["output_tokens"] += r.usage.output_tokens
                run_usage["api_calls"] += 1
                if r.stop_reason in ("refusal", "max_tokens"):
                    raise RuntimeError(f"enrichment call ended with {r.stop_reason}")
                return json.loads(next(b.text for b in r.content if b.type == "text"))

            # events + chapter summary — one call per chapter, with prose
            processed_books: set[int] = set()  # books actually (re)enriched
            for c in chapters:
                try:
                    data = call(EVENTS_PROMPT, json.dumps(
                        {k: v for k, v in c.items() if k != "content_hash"},
                        ensure_ascii=False), _EVENTS_SCHEMA)
                    # a quote only survives if it is verbatim chapter prose
                    prose_norm = norm_quote(" ".join(t["text"] for t in c["prose"]))
                    for ev in data.get("events", []):
                        q = ev.get("quote")
                        if q and norm_quote(q) not in prose_norm:
                            log.info("rejected unverified quote for %r", ev.get("title"))
                            ev["quote"] = None
                    self._store_events(db, c, data.get("events", []))
                    summary = (data.get("chapter_summary") or "").strip()
                    if summary:
                        db.execute(
                            """INSERT INTO chapter_summaries (book_number, chapter_number, summary)
                               VALUES (?,?,?) ON CONFLICT(book_number, chapter_number)
                               DO UPDATE SET summary = excluded.summary""",
                            (c["book_number"], c["chapter_number"], summary))
                    _set_state(db, f"events:{c['book_number']}.{c['chapter_number']}",
                               c["content_hash"])
                    db.commit()
                    processed_books.add(c["book_number"])
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

            # relationship natures — evidence-based, quote-verified. Runs on
            # ENRICH_REL_MODEL when set: direction inference is the one
            # enrichment task where the small extraction model demonstrably
            # fails (nulls with decisive evidence in hand, flipped
            # older/younger), and the pass is tiny relative to extraction.
            rel_model = cfg.enrich_rel_model or None
            for r in rels:
                try:
                    data = label_relationships(
                        lambda s, u, sc: call(s, u, sc, model=rel_model), r)
                    self._store_relationships(db, r, data)
                    _set_state(db, f"rels:{r['name']}", r["content_hash"])
                    db.commit()
                except Exception as e:
                    log.warning("relationship enrichment failed for %s: %s", r["name"], e)
                self.status["done"] += 1

            # location gazetteer — v2 (ENABLE_LOCATION_V2) resolves per book
            # in src.location_resolve with its own state keys and cost
            # surface ("locations_v2", logged inside resolve_locations, NOT
            # this run's "enrich" line). Non-fatal by convention: on failure
            # the gazetteer is merely stale and can be rebuilt with
            # scripts/resolve_locations.py.
            if loc_batches and getattr(cfg, "enable_location_v2", False):
                done_before = self.status["done"]
                try:
                    from src.location_resolve import resolve_locations

                    def _loc_tick(*_args):
                        self.status["done"] = min(
                            self.status["done"] + 1,
                            done_before + len(loc_batches))

                    resolve_locations(db, cfg, client, on_batch=_loc_tick)
                except Exception as e:
                    log.warning("location v2 resolution failed (gazetteer "
                                "may be stale; run "
                                "scripts/resolve_locations.py): %s", e)
                self.status["done"] = done_before + len(loc_batches)
            # v1 gazetteer — sequential batches share the growing canon
            elif loc_batches:
                known: dict[str, str | None] = {}
                failed_batches = 0
                for batch in loc_batches:
                    try:
                        data = call(LOC_PROMPT, json.dumps({
                            "known_places": [
                                {"place": k, "parent": v}
                                for k, v in sorted(known.items())],
                            "locations": batch,
                        }, ensure_ascii=False), _LOC_SCHEMA)
                        valid = set(batch)
                        for m in data.get("mappings", []):
                            if m.get("raw") not in valid:
                                continue
                            place, parent = m.get("place"), m.get("parent")
                            if place:
                                known.setdefault(place, parent)
                            db.execute(
                                "INSERT INTO location_map (raw, place, parent) "
                                "VALUES (?,?,?) ON CONFLICT(raw) DO UPDATE SET "
                                "place = excluded.place, parent = excluded.parent",
                                (m["raw"], place, parent))
                        db.commit()
                    except Exception as e:
                        failed_batches += 1
                        log.warning("location batch failed: %s", e)
                    self.status["done"] += 1
                if not failed_batches:
                    _set_state(db, "locmap", loc_hash)
                    db.commit()

            # chronology — re-resolve story_year for just the books whose
            # chapters were (re)enriched, so ?order=story stays current after
            # a resync with no manual step. Its spend goes to the existing
            # "chronology" cost surface (logged inside resolve_chronology),
            # NOT to this run's "enrich" line. Non-fatal by convention: on
            # failure story order is merely stale and can be rebuilt with
            # scripts/resolve_chronology.py.
            if chrono_books:
                done_before = self.status["done"]
                affected = sorted(processed_books)
                if affected:
                    try:
                        from src.chronology import resolve_chronology

                        def _chrono_tick(*_args):
                            self.status["done"] = min(
                                self.status["done"] + 1,
                                done_before + len(chrono_books))

                        chrono_stats: dict = {}
                        resolve_chronology(db, cfg, client,
                                           books=set(affected),
                                           on_book=_chrono_tick,
                                           stats=chrono_stats)
                        try:
                            from . import audit
                            audit.log_event(
                                "chronology_resolved",
                                "story chronology re-resolved after enrichment",
                                books=chrono_stats.get("books_resolved",
                                                       affected),
                                chapters_upserted=chrono_stats.get("upserts", 0),
                                cost_usd=chrono_stats.get("cost_usd", 0.0))
                        except Exception:
                            pass
                    except Exception as e:
                        log.warning("chronology resolution failed for books %s "
                                    "(story order may be stale; run "
                                    "scripts/resolve_chronology.py): %s",
                                    affected, e)
                self.status["done"] = done_before + len(chrono_books)

            self._reconcile_directions(db)
            self.status["state"] = "done"
            try:
                from . import audit
                audit.log_event("enrich_finished", "enrichment run finished",
                                total=self.status["total"],
                                cost_usd=self.status["cost_usd"])
            except Exception:
                pass
            try:
                from . import notify
                notify.add("extraction_complete", "Enrichment complete",
                           f"{self.status['total']} tasks processed "
                           f"(${self.status['cost_usd']:.2f}). Events, summaries, "
                           "and profiles are up to date.",
                           action_url="/?pane=timeline")
            except Exception:
                log.exception("failed to write enrichment notification")
        except Exception as e:
            log.exception("enrichment run failed")
            self.status.update(state="error", error=str(e))
            try:
                from . import audit
                audit.log_event("enrich_failed", "enrichment run failed",
                                error=str(e))
            except Exception:
                pass
            try:
                from . import notify
                notify.add("error", "Enrichment failed", str(e))
            except Exception:
                pass
        finally:
            if run_usage["api_calls"]:  # one aggregate line per run with spend
                log_cost(cfg, surface="enrich", model=cfg.extraction_model,
                         usage=run_usage, cost_usd=self.status["cost_usd"],
                         latency_ms=int((time.monotonic() - t0) * 1000),
                         extra={"api_calls": run_usage["api_calls"],
                                "state": self.status["state"]})

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
                       participants_json, knowledge_json, source_chunk_ids_json,
                       quote)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (book, ch, pos, ev["title"], ev["type"], ev["granularity"],
                 chapter.get("date_line"), ev.get("summary"), location,
                 json.dumps(participants, ensure_ascii=False),
                 json.dumps(knowledge[:12], ensure_ascii=False),
                 json.dumps(sources), ev.get("quote")))

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
        me_first = payload["name"].split()[0].lower()
        kw_re = re.compile("|".join(re.escape(k) for k in _REL_KEYWORDS))
        # first-person possessive claim ("my girlfriend", "my little
        # brother's girlfriend") — only valid evidence when the narrator IS
        # the profile owner; otherwise it's someone else's relationship
        poss_re = re.compile(r"\bmy\s+(?:\w+'?s?\s+){0,2}(?:%s)"
                             % "|".join(re.escape(k) for k in _REL_KEYWORDS))
        verified = []
        for r in data.get("relationships", []):
            name = r.get("name")
            if name not in valid:
                continue
            nature, evidence = r.get("nature"), r.get("evidence")
            snippets = payload["evidence"].get(name, [])
            src = next((s for s in snippets
                        if evidence and norm(evidence) in norm(s)), None)
            ok = bool(nature and evidence and src)
            reason = "quote not found in snippets"
            if ok:
                ev_norm = norm(evidence)
                # evidence must actually contain a relationship word — an
                # atmospheric quote cannot establish a nature
                if not kw_re.search(ev_norm):
                    ok, reason = False, "no relationship keyword in evidence"
                elif re.search(r"\byour\s+(?:\w+'?s?\s+){0,2}(?:%s)"
                               % "|".join(re.escape(k) for k in _REL_KEYWORDS),
                               ev_norm):
                    # second-person possessive ("your girlfriend") describes
                    # the ADDRESSEE, whose identity we cannot verify — null
                    ok, reason = False, "second-person possessive evidence"
                else:
                    m = re.search(r"\[narrator: ([^\]]+)\]", src)
                    narrator = (m.group(1).split()[0].lower() if m else "")
                    if poss_re.search(ev_norm) and narrator != me_first:
                        ok, reason = False, (
                            f"first-person possessive narrated by {narrator!r},"
                            f" not the profile owner")
            if nature and not ok:
                log.info("rejected nature %r for %s -> %s (%s)",
                         nature, payload["name"], name, reason)
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

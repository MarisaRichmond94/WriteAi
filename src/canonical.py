"""Character-name canonicalization.

Raw extraction tags (the `characters` table) are noisy: the same person under
several spellings, plus occasional names the model invented that appear
nowhere in the prose ("Emma Gatlin", "Brianna"). This layer derives clean
character entities WITHOUT ever modifying the raw tables and WITHOUT any AI
judgment — every rule is mechanical and auditable:

  1. GROUNDING — a name variant is legitimate only if its exact string
     occurs somewhere in the actual prose, or it matches a POV header name
     (chapter headers are authoritative: in first-person scenes the
     narrator's name may never appear in prose).
  2. PARENTHETICALS — "Emma (mentioned)" folds to "Emma"; "Brianna (Bri)"
     keeps whichever part is grounded ("Bri").
  3. MERGING — a grounded single-token variant attaches to a grounded full
     name only when exactly one full name starts with that token
     ("Noah" -> "Noah Gatlin"). Ambiguous fragments are left alone.
  4. UNGROUNDED variants are remapped to the unique grounded entity whose
     first token they contain ("Emma Gatlin" -> Emma's entity), preserving
     the presence fact but discarding the invented spelling; otherwise the
     tag is QUARANTINED (excluded from the UI, listed for review).
  5. Relational descriptors ("Jared's father") stay separate entities of
     kind "descriptor" unless the user maps them.
  6. The user's decisions in writer_data/character_map.json are applied
     FIRST and are never overridden by any heuristic. They survive
     re-ingestion because they're keyed by name, not by index state.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from server import writer_store

log = logging.getLogger(__name__)

_PAREN_RE = re.compile(r"^(.*?)\s*\((.*?)\)\s*$")
_NON_NAME_PARENS = {"mentioned", "referenced", "unnamed", "unseen", "implied",
                    "voice", "flashback", "memory", "photo", "deceased"}

# ── personhood classification ───────────────────────────────────────────────
# Extraction tags like "CFO", "Board members", "The man", "other students"
# are grounded in prose but aren't named people. Classified mechanically as
# kind="generic" and excluded from character UIs (recoverable via the
# Raw AI view or by assigning them to a real character).

_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "coach", "principal",
               "officer", "detective", "professor", "father", "sister",
               "judge", "captain", "sergeant", "deputy", "nurse", "agent"}

_DETERMINERS = {"the", "a", "an", "other", "others", "some", "several",
                "various", "both", "two", "three", "four", "many", "another",
                "their", "his", "her", "my", "our", "one", "unnamed",
                "unknown", "unidentified", "masked", "mysterious", "random",
                "new", "old", "young", "opposing", "rival", "fellow"}

_ROLE_WORDS = {
    # titles / occupations
    "cfo", "ceo", "coo", "cto", "vp", "president", "chairman", "chairwoman",
    "judge", "principal", "coach", "teacher", "counselor", "therapist",
    "doctor", "physician", "nurse", "surgeon", "paramedic", "medic",
    "officer", "officers", "cop", "cops", "police", "policeman", "detective",
    "detectives", "sheriff", "deputy", "guard", "guards", "bodyguard",
    "attorney", "lawyer", "lawyers", "prosecutor", "bailiff", "jury",
    "secretary", "receptionist", "assistant", "operator", "dispatcher",
    "waiter", "waitress", "bartender", "barista", "cashier", "clerk",
    "driver", "chauffeur", "pilot", "captain", "conductor",
    "reporter", "reporters", "journalist", "anchor", "interviewer",
    "referee", "umpire", "announcer", "scout", "recruiter", "trainer",
    "manager", "boss", "employee", "employees", "worker", "workers",
    "staff", "staffer", "janitor", "librarian", "chef", "cook",
    "bully", "bullies", "stranger", "strangers", "passerby", "bystander",
    "bystanders", "neighbor", "neighbors", "landlord", "tenant",
    "pastor", "priest", "reverend", "chaplain", "monk",
    "soldier", "soldiers", "veteran", "marine", "sailor",
    "psychiatrist", "psychologist", "specialist", "expert", "consultant",
    "bouncer", "dealer", "thug", "thugs", "goon", "goons", "henchman",
    "henchmen", "attacker", "attackers", "assailant", "intruder", "burglar",
    "kidnapper", "shooter", "gunman", "sniper", "voice", "figure", "silhouette",
    # people-group nouns
    "man", "men", "woman", "women", "boy", "boys", "girl", "girls",
    "kid", "kids", "child", "children", "teen", "teens", "teenager",
    "teenagers", "adult", "adults", "person", "people", "guy", "guys",
    "lady", "ladies", "gentleman", "gentlemen", "folks", "crowd", "mob",
    "student", "students", "classmate", "classmates", "schoolmate",
    "player", "players", "teammate", "teammates", "team", "squad",
    "member", "members", "board", "committee", "council", "panel",
    "family", "families", "parents", "grandparents", "siblings", "brothers",
    "sisters", "relatives", "cousins", "twins", "couple", "pair", "group",
    "gang", "crew", "clique", "friends", "buddies", "peers", "onlookers",
    "spectators", "audience", "patrons", "customers", "guests", "visitors",
    "patients", "victims", "witnesses", "suspects", "inmates", "prisoners",
    "nurses", "doctors", "teachers", "authorities", "paramedics",
    "operators", "clerks", "servers",
}


def _is_generic(name: str) -> bool:
    """True when a grounded tag is a role/group description, not a named
    person. Purely mechanical; honorific + proper name is exempt."""
    tokens = name.split()
    if not tokens:
        return True
    lower = [t.strip(".,").lower() for t in tokens]
    # "Mr. Ryan", "Coach West", "Dr. Patel" — honorific + capitalized
    # non-role token is a real named character
    if (len(tokens) >= 2 and lower[0] in _HONORIFICS
            and tokens[1][:1].isupper() and lower[1] not in _ROLE_WORDS
            and lower[1] not in _DETERMINERS):
        return False
    # any lowercase token -> descriptive phrase ("police operator",
    # "other students in locker room")
    if any(t[:1].islower() for t in tokens):
        return True
    # determiner-led phrases ("The man", "Other Students")
    if lower[0] in _DETERMINERS:
        return True
    # every token is a role/group word ("CFO", "Board Members", "Judge")
    if all(t in _ROLE_WORDS or t in _DETERMINERS for t in lower):
        return True
    return False


@dataclass
class Entity:
    name: str                       # canonical display name
    aliases: list[str] = field(default_factory=list)
    kind: str = "character"         # "character" | "descriptor"
    chunk_ids: set = field(default_factory=set)
    is_pov: bool = False
    pov_chunks: int = 0

    def to_summary(self, chunk_meta: dict) -> dict:
        books = sorted({chunk_meta[cid][0] for cid in self.chunk_ids if cid in chunk_meta})
        chapters = sorted({(chunk_meta[cid][0], chunk_meta[cid][1])
                           for cid in self.chunk_ids if cid in chunk_meta})
        return {
            "id": self.name,
            "name": self.name,
            "aliases": self.aliases,
            "kind": self.kind,
            "books": books,
            "chunk_count": len(self.chunk_ids),
            "chapter_count": len(chapters),
            "is_pov": self.is_pov,
            "pov_chunk_count": self.pov_chunks,
        }


class Canonicalizer:
    """Builds and caches the entity view; rebuild when data or map changes."""

    def __init__(self, db: sqlite3.Connection):
        import threading
        self.db = db
        self._build_lock = threading.Lock()
        self._built_at = 0.0
        self._map_state: str = ""
        self.entities: dict[str, Entity] = {}
        self.variant_to_entity: dict[str, str] = {}
        self.quarantined: list[dict] = []
        self.chunk_entities: dict[str, set] = defaultdict(set)
        self.chunk_meta: dict[str, tuple] = {}  # chunk_id -> (book, chapter)

    # ── public API ──────────────────────────────────────────────────────────

    def ensure_built(self) -> None:
        # The whole check runs under the lock: this instance's connection is
        # shared across request threads, and even the cheap COUNT query
        # corrupts if two threads interleave on it.
        with self._build_lock:
            cmap = writer_store.character_map()
            state = repr(sorted(cmap.get("map", {}).items())) + repr(sorted(cmap.get("hidden", [])))
            row_count = self.db.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
            state += f"|rows={row_count}"
            if state != self._map_state or time.time() - self._built_at > 3600:
                self._build(cmap)
                self._map_state = state
                self._built_at = time.time()

    def resolve(self, name: str) -> str | None:
        """Raw variant -> canonical entity name (None if quarantined/hidden)."""
        self.ensure_built()
        return self.variant_to_entity.get(name)

    def visible_entities(self) -> list[Entity]:
        self.ensure_built()
        hidden = set(writer_store.character_map().get("hidden", []))
        return sorted((e for e in self.entities.values() if e.name not in hidden),
                      key=lambda e: -len(e.chunk_ids))

    def co_occurrence(self, name: str) -> list[tuple[str, int]]:
        """Scene-sharing counts with every other visible entity."""
        self.ensure_built()
        me = self.entities.get(name)
        if me is None:
            return []
        counts: Counter = Counter()
        for cid in me.chunk_ids:
            for other in self.chunk_entities.get(cid, ()):
                if other != name:
                    counts[other] += 1
        hidden = set(writer_store.character_map().get("hidden", []))
        return [(n, c) for n, c in counts.most_common()
                if n not in hidden
                and self.entities.get(n) is not None
                and self.entities[n].kind == "character"]

    # ── build ───────────────────────────────────────────────────────────────

    def _grounded(self, name: str, pov_names: set[str]) -> bool:
        if not name:
            return False
        # POV headers are authoritative — but only for the exact header name,
        # or a bare first name ("Emma"). A multi-token name that merely SHARES
        # a first token ("Emma Gatlin") must prove itself in the prose,
        # otherwise invented surnames slip through.
        if name in pov_names:
            return True
        if len(name.split()) == 1 and name in {p.split()[0] for p in pov_names}:
            return True
        row = self.db.execute("SELECT 1 FROM chunks WHERE text LIKE ? LIMIT 1",
                              (f"%{name}%",)).fetchone()
        return row is not None

    def _build(self, cmap: dict) -> None:
        log.info("building canonical character view…")
        user_map: dict[str, str] = cmap.get("map", {})

        self.chunk_meta = {
            cid: (b, ch) for cid, b, ch in self.db.execute(
                "SELECT chunk_id, book_number, chapter_number FROM chunks")
        }
        pov_names = {r[0] for r in self.db.execute(
            "SELECT DISTINCT pov_character FROM chunks WHERE pov_character IS NOT NULL")}
        pov_by_chunk = dict(self.db.execute(
            "SELECT chunk_id, pov_character FROM chunks"))

        raw: dict[str, set] = defaultdict(set)   # variant -> chunk_ids
        for name, cid in self.db.execute("SELECT name, chunk_id FROM characters"):
            raw[name.strip()].add(cid)

        grounded_cache: dict[str, bool] = {}

        def grounded(n: str) -> bool:
            if n not in grounded_cache:
                grounded_cache[n] = self._grounded(n, pov_names)
            return grounded_cache[n]

        # Pass 1 — normalize each raw variant to a working name (or defer).
        #   normalized: working_name -> set(chunk_ids), merged across raw forms
        #   variant_working: raw variant -> working name (for resolve())
        normalized: dict[str, set] = defaultdict(set)
        variant_working: dict[str, str] = {}
        deferred: list[tuple[str, set]] = []      # ungrounded, retry in pass 3
        for variant, cids in raw.items():
            if variant in user_map:               # user decision wins outright
                normalized[user_map[variant]] |= cids
                variant_working[variant] = user_map[variant]
                continue
            # candidate simplifications, first grounded one wins:
            candidates = [variant]
            m = _PAREN_RE.match(variant)
            if m:
                base, paren = m.group(1).strip(), m.group(2).strip()
                candidates = [base]
                if paren.lower() not in _NON_NAME_PARENS:
                    candidates.append(paren)
            # quoted nicknames: "Bernice 'Bee' Everly" -> "Bernice Everly", "Bee"
            if "'" in variant or "‘" in variant or '"' in variant:
                stripped = re.sub(r"\s*['‘’\"](.*?)['‘’\"]\s*", " ",
                                  variant).strip()
                nick = re.search(r"['‘’\"](.*?)['‘’\"]", variant)
                if stripped and stripped != variant:
                    candidates.append(re.sub(r"\s+", " ", stripped))
                if nick and nick.group(1):
                    candidates.append(nick.group(1))
            name = next((c for c in candidates if "'s " not in c and grounded(c)), None)
            if name is None and "'s " in candidates[0]:
                name = candidates[0]              # relational descriptor
            # the user's map applies to normalized names too, so variants
            # that RESOLVE to a mapped name ("Brianna (Bri)" -> "Bri")
            # follow the same merge as the name itself
            if name is not None and name in user_map:
                name = user_map[name]
            if name is not None:
                normalized[name] |= cids
                variant_working[variant] = name
            else:
                deferred.append((variant, cids))

        # Pass 2 — group grounded variants into entities.
        multi = [n for n in normalized if " " in n and "'s " not in n]
        single = [n for n in normalized if " " not in n]
        descriptors = [n for n in normalized if "'s " in n]

        # Merge full-name heads that are first-token-anchored subsequences of
        # a longer head — "Chase Gatlin" and "Chase Ryder Gatlin" are one
        # person. Anchoring on the first name keeps "Michael Gatlin" (the
        # father) from folding into "Jared Michael Gatlin" (the son). The
        # most-frequent spelling becomes the display name.
        def _subseq(short: list[str], long: list[str]) -> bool:
            it = iter(long)
            return all(tok in it for tok in short)

        head_canon: dict[str, str] = {h: h for h in multi}
        for h in sorted(multi, key=lambda n: len(n.split())):
            ht = h.split()
            longer = [o for o in multi if o != h and o.split()[0] == ht[0]
                      and len(o.split()) > len(ht) and _subseq(ht, o.split())]
            if len(longer) == 1:
                # union: point the less frequent name at the more frequent one
                a, b = h, longer[0]
                keep = a if len(normalized[a]) >= len(normalized[b]) else b
                drop = b if keep == a else a
                for k, v in list(head_canon.items()):
                    if v == drop:
                        head_canon[k] = keep
                head_canon[drop] = keep

        head_by_first: dict[str, list[str]] = defaultdict(list)
        for h in multi:
            canon_h = head_canon[h]
            if canon_h not in head_by_first[h.split()[0]]:
                head_by_first[h.split()[0]].append(canon_h)

        entity_of: dict[str, str] = {h: head_canon[h] for h in multi}
        for s in single:
            heads = head_by_first.get(s, [])
            entity_of[s] = heads[0] if len(heads) == 1 else s
        for d in descriptors:
            entity_of[d] = d

        # Pass 3 — ungrounded variants: fold into the unique entity whose
        # first token matches; otherwise quarantine.
        self.quarantined = []
        for variant, cids in deferred:
            first = variant.split()[0].strip("'s")
            heads = head_by_first.get(first, [])
            if len(heads) == 1:
                target = user_map.get(heads[0], heads[0])
                normalized[target] |= cids
                variant_working[variant] = target
                entity_of.setdefault(target, target)
                log.debug("remapped ungrounded %r -> %r", variant, target)
            elif first in entity_of:              # matches a single-token entity
                target = user_map.get(first, first)
                normalized[target] |= cids
                variant_working[variant] = target
            else:
                self.quarantined.append({
                    "name": variant,
                    "chunk_count": len(cids),
                    "reason": "name not found in prose and no unambiguous match",
                })

        # Assemble entities.
        self.entities = {}
        self.variant_to_entity = {}
        self.chunk_entities = defaultdict(set)
        groups: dict[str, Entity] = {}
        user_targets = set(user_map.values())  # names the user assigned INTO

        def classify(canon: str) -> str:
            if canon in user_targets:
                return "character"     # the user's choice outranks heuristics
            if "'s " in canon:
                return "descriptor"    # "Jared's brother"
            if _is_generic(canon):
                return "generic"       # "CFO", "Board members", "The man"
            return "character"

        for name, cids in normalized.items():
            canon = entity_of.get(name, name)
            e = groups.setdefault(canon, Entity(name=canon, kind=classify(canon)))
            if name != canon and name not in e.aliases:
                e.aliases.append(name)
            e.chunk_ids |= cids
            self.variant_to_entity[name] = canon
        # every raw variant resolves through its working name
        for variant, working in variant_working.items():
            self.variant_to_entity[variant] = entity_of.get(working, working)

        # user-merged variants become visible aliases of their target
        # ("Bri" -> "Brielle Draper" shows as: Brielle Draper, aka Bri) —
        # but junk phrases assigned to a character don't become alias pills
        for variant, target in user_map.items():
            e = groups.get(target)
            if (e is not None and variant != target
                    and variant not in e.aliases
                    and "'s " not in variant and not _is_generic(variant)):
                e.aliases.append(variant)

        for e in groups.values():
            names = {e.name, *e.aliases}
            firsts = {n.split()[0] for n in names}
            e.is_pov = any(p in names or p.split()[0] in firsts for p in pov_names)
            if e.is_pov:
                e.pov_chunks = sum(
                    1 for cid in e.chunk_ids
                    if (pov_by_chunk.get(cid) in names
                        or (pov_by_chunk.get(cid) or "").split()[0] in firsts))
            for cid in e.chunk_ids:
                self.chunk_entities[cid].add(e.name)

        self.entities = groups
        log.info("canonical view: %d entities (%d quarantined tags)",
                 len(groups), sum(q["chunk_count"] for q in self.quarantined))

"""Build golden evaluation candidates for the Dark Horse series RAG system.

Reads data/series_metadata.sqlite (READ-ONLY) and emits ~100 candidate eval
items to eval/golden_candidates.jsonl, spread across the five query types
handled by src.query_router.classify():

    temporal_knowledge  <- character_knowledge rows
    sentiment           <- emotional_beats in chunk metadata_json
    continuity          <- foreshadowing / unresolved_questions rows
    lookup              <- characters / locations side tables
    general             <- events rows

Every emitted question is passed through classify() and only kept if it
routes to the intended qtype, so the golden phrasing is guaranteed to hit
the intended retrieval path.

Deterministic: no randomness; selection is fixed SQL ordering + per-book
quotas. Running twice produces byte-identical output.

Usage:
    .venv/bin/python eval/build_golden_candidates.py            # regenerate candidates
    .venv/bin/python eval/build_golden_candidates.py --verify   # verify eval/golden_set.jsonl
    .venv/bin/python eval/build_golden_candidates.py --verify eval/golden_candidates.jsonl
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.query_router import classify  # noqa: E402

DB_PATH = REPO_ROOT / "data" / "series_metadata.sqlite"
OUT_PATH = REPO_ROOT / "eval" / "golden_candidates.jsonl"

BOOKS = [1, 2, 3, 4, 5]

# Display names used when phrasing questions (short, natural author phrasing).
MAIN_NAMES = [
    "Jared", "Emma", "Noah", "Chase", "Quinn", "Hiro", "Bri", "Wren",
    "Austin", "Calico", "Cat", "Aashil", "Mr. Ryan", "Dr. Barba",
]
_NAME_PATTERNS = {n: re.compile(rf"\b{re.escape(n)}\b") for n in MAIN_NAMES}

_STOPWORDS = {
    "about", "after", "again", "against", "because", "before", "being",
    "between", "could", "doesn", "during", "every", "front", "going",
    "having", "himself", "herself", "later", "might", "other", "should",
    "since", "something", "their", "there", "these", "things", "think",
    "those", "through", "toward", "under", "until", "wants", "where",
    "which", "while", "whose", "would", "years",
}

_PROPER_FIRST: set[str] = set()

_EMOTIONS = [
    "guilty", "hurt", "angry", "jealous", "protective", "betrayed",
    "relieved", "anxious", "frustrated", "irritated", "torn", "grateful",
    "ashamed", "nervous", "worried", "conflicted", "resentful", "afraid",
    "suspicious", "comforted", "loved", "supported", "abandoned",
]


def connect() -> sqlite3.Connection:
    # mode=ro guarantees this script can never write to the database.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def scope_str(plan) -> str | None:
    """Serialize the Scope classify() derived, for reference in the item."""
    s = plan.scope
    if s.book_min is None and s.book_max is None:
        return None
    lo = s.book_min if s.book_min is not None else s.book_max
    hi = s.book_max
    out = f"book:{hi}" if lo == hi else f"books:{lo}-{hi}"
    if s.chapter_max is not None:
        out += f",chapter:{s.chapter_max}"
    return out


def key_terms(text: str, limit: int = 3) -> list[str]:
    """Deterministically pick up to `limit` salient words from source text."""
    words = re.findall(r"[A-Za-z']{5,}", text)
    seen: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in _STOPWORDS or w in ("Jared", "Emma", "Noah"):
            continue
        if lw not in [s.lower() for s in seen]:
            seen.append(w if w[0].isupper() else lw)
        if len(seen) >= limit:
            break
    return seen or [text.split()[0].lower()]


def names_in(text: str, exclude: str = "") -> list[str]:
    hits = [n for n in MAIN_NAMES if _NAME_PATTERNS[n].search(text)]
    return [n for n in hits if n != exclude and not exclude.startswith(n)]


def make_item(prefix, seq, question, qtype, chunk_ids, citations, mention, notes):
    plan = classify(question)
    if plan.qtype != qtype:
        return None  # phrasing would mis-route; caller skips this row
    # De-dup citations preserving order.
    cites, seen = [], set()
    for c in citations:
        t = (int(c[0]), int(c[1]))
        if t not in seen:
            seen.add(t)
            cites.append([t[0], t[1]])
    return {
        "id": f"{prefix}-{seq:03d}",
        "question": question,
        "qtype": qtype,
        "scope": scope_str(plan),
        "expected_chunk_ids": list(chunk_ids),
        "expected_citations": cites,
        "answer_must_mention": mention[:4],
        "tags": [],
        "notes": notes,
    }


# --------------------------------------------------------------------------
# temporal_knowledge: from character_knowledge
# --------------------------------------------------------------------------

def gen_temporal(con) -> list[dict]:
    rows = con.execute(
        """SELECT ck.rowid, ck.chunk_id, ck.character, ck.learns,
                  c.book_number, c.chapter_number
           FROM character_knowledge ck JOIN chunks c USING(chunk_id)
           WHERE length(ck.learns) BETWEEN 35 AND 130
           ORDER BY c.book_number, ck.chunk_id, ck.rowid""").fetchall()
    items, seq = [], 1
    quota_a = Counter()  # "what does X know about Y by the end of book N"
    quota_b = Counter()  # "by the end of chapter M in book N, what has X learned"
    used_pairs = set()
    for rowid, cid, char, learns, bk, ch in rows:
        if char not in MAIN_NAMES:
            continue
        others = names_in(learns, exclude=char)
        if others and quota_a[bk] < 2:
            other = others[0]
            pair = (char, other, bk)
            if pair in used_pairs:
                continue
            q = f"What does {char} know about {other} by the end of book {bk}?"
            item = make_item("tk", seq, q, "temporal_knowledge", [cid],
                             [(bk, ch)], key_terms(learns),
                             f"derived from character_knowledge rowid {rowid}: {learns!r}")
            if item:
                used_pairs.add(pair)
                items.append(item)
                quota_a[bk] += 1
                seq += 1
        elif not others and quota_b[bk] < 2:
            q = (f"By the end of chapter {ch} in book {bk}, "
                 f"what has {char} learned?")
            item = make_item("tk", seq, q, "temporal_knowledge", [cid],
                             [(bk, ch)], key_terms(learns),
                             f"derived from character_knowledge rowid {rowid}: {learns!r}")
            if item:
                items.append(item)
                quota_b[bk] += 1
                seq += 1
        if len(items) >= 20:
            break
    return items


# --------------------------------------------------------------------------
# sentiment: from emotional_beats in chunk metadata
# --------------------------------------------------------------------------

def gen_sentiment(con) -> list[dict]:
    rows = con.execute(
        """SELECT chunk_id, book_number, chapter_number, metadata_json
           FROM chunks ORDER BY book_number, chunk_id""").fetchall()
    items, seq = [], 1
    quota = Counter()
    used_pairs = set()
    for cid, bk, ch, mj in rows:
        if quota[bk] >= 4:
            continue
        md = json.loads(mj or "{}")
        for beat in md.get("emotional_beats") or []:
            hits = [n for n in MAIN_NAMES if _NAME_PATTERNS[n].search(beat)]
            if len(hits) < 2:
                continue
            a, b = hits[0], hits[1]
            if (a, b, bk) in used_pairs or not beat.startswith(a):
                continue
            emotions = [e for e in _EMOTIONS if re.search(rf"\b{e}\b", beat)]
            if not emotions:
                continue
            q = f"How does {a} feel about {b} in book {bk}?"
            item = make_item("sn", seq, q, "sentiment", [cid], [(bk, ch)],
                             emotions[:2] + [b],
                             f"derived from emotional_beats of chunk {cid}: {beat!r}")
            if item:
                used_pairs.add((a, b, bk))
                items.append(item)
                quota[bk] += 1
                seq += 1
                break
        if len(items) >= 20:
            break
    return items


# --------------------------------------------------------------------------
# continuity: from foreshadowing and unresolved_questions
# --------------------------------------------------------------------------

def gen_continuity(con) -> list[dict]:
    items, seq = [], 1
    # Foreshadowing: chapters with the most planted details, 2 per book.
    fs = con.execute(
        """SELECT c.book_number, c.chapter_number, COUNT(*) n,
                  group_concat(DISTINCT f.chunk_id)
           FROM foreshadowing f JOIN chunks c USING(chunk_id)
           GROUP BY c.book_number, c.chapter_number
           HAVING n >= 3
           ORDER BY c.book_number, n DESC, c.chapter_number""").fetchall()
    per_book = Counter()
    for bk, ch, n, cids in fs:
        if per_book[bk] >= 2:
            continue
        detail = con.execute(
            """SELECT f.detail FROM foreshadowing f JOIN chunks c USING(chunk_id)
               WHERE c.book_number=? AND c.chapter_number=?
               ORDER BY length(f.detail) DESC, f.rowid LIMIT 1""",
            (bk, ch)).fetchone()[0]
        q = f"What foreshadowing is set up in chapter {ch} of book {bk}?"
        item = make_item("ct", seq, q, "continuity",
                         sorted(cids.split(","))[:4], [(bk, ch)],
                         key_terms(detail),
                         f"chapter has {n} foreshadowing rows; e.g. {detail!r}")
        if item:
            items.append(item)
            per_book[bk] += 1
            seq += 1
    # Unresolved questions: chapters with the most open threads, 2 per book.
    uq = con.execute(
        """SELECT c.book_number, c.chapter_number, COUNT(*) n,
                  group_concat(DISTINCT u.chunk_id)
           FROM unresolved_questions u JOIN chunks c USING(chunk_id)
           GROUP BY c.book_number, c.chapter_number
           HAVING n >= 3
           ORDER BY c.book_number, n DESC, c.chapter_number""").fetchall()
    per_book = Counter()
    for bk, ch, n, cids in uq:
        if per_book[bk] >= 2:
            continue
        question_row = con.execute(
            """SELECT u.question FROM unresolved_questions u JOIN chunks c USING(chunk_id)
               WHERE c.book_number=? AND c.chapter_number=?
               ORDER BY length(u.question) DESC, u.rowid LIMIT 1""",
            (bk, ch)).fetchone()[0]
        q = (f"What questions are left unresolved at the end of "
             f"chapter {ch} in book {bk}?")
        item = make_item("ct", seq, q, "continuity",
                         sorted(cids.split(","))[:4], [(bk, ch)],
                         key_terms(question_row),
                         f"chapter has {n} unresolved_questions rows; e.g. {question_row!r}")
        if item:
            items.append(item)
            per_book[bk] += 1
            seq += 1
    return items


# --------------------------------------------------------------------------
# lookup: from characters / locations side tables
# --------------------------------------------------------------------------

def gen_lookup(con) -> list[dict]:
    items, seq = [], 1
    # Characters with a small, checkable scene count per book (2-10 chunks).
    ch_rows = con.execute(
        """SELECT ch.name, c.book_number, COUNT(DISTINCT ch.chunk_id) n
           FROM characters ch JOIN chunks c USING(chunk_id)
           GROUP BY ch.name, c.book_number
           HAVING n BETWEEN 2 AND 10
           ORDER BY c.book_number, n DESC, ch.name""").fetchall()
    per_book = Counter()
    for name, bk, n in ch_rows:
        if per_book[bk] >= 2 or name not in MAIN_NAMES:
            continue
        cids = [r[0] for r in con.execute(
            """SELECT DISTINCT ch.chunk_id FROM characters ch
               JOIN chunks c USING(chunk_id)
               WHERE ch.name=? AND c.book_number=? ORDER BY ch.chunk_id""",
            (name, bk))]
        cites = con.execute(
            """SELECT DISTINCT c.book_number, c.chapter_number
               FROM characters ch JOIN chunks c USING(chunk_id)
               WHERE ch.name=? AND c.book_number=?
               ORDER BY c.chapter_number""", (name, bk)).fetchall()
        q = f"List every scene where {name} appears in book {bk}."
        item = make_item("lk", seq, q, "lookup", cids, cites, [name],
                         f"characters table: {name!r} tagged in {n} chunks of book {bk}")
        if item:
            items.append(item)
            per_book[bk] += 1
            seq += 1
    # Locations with 2-8 chunks per book.
    loc_rows = con.execute(
        """SELECT l.name, c.book_number, COUNT(DISTINCT l.chunk_id) n
           FROM locations l JOIN chunks c USING(chunk_id)
           WHERE length(l.name) BETWEEN 8 AND 40 AND l.name NOT LIKE '%-%'
           GROUP BY l.name, c.book_number
           HAVING n BETWEEN 2 AND 8
           ORDER BY c.book_number, n DESC, l.name""").fetchall()
    per_book = Counter()
    for name, bk, n in loc_rows:
        if per_book[bk] >= 2:
            continue
        cids = [r[0] for r in con.execute(
            """SELECT DISTINCT l.chunk_id FROM locations l
               JOIN chunks c USING(chunk_id)
               WHERE l.name=? AND c.book_number=? ORDER BY l.chunk_id""",
            (name, bk))]
        cites = con.execute(
            """SELECT DISTINCT c.book_number, c.chapter_number
               FROM locations l JOIN chunks c USING(chunk_id)
               WHERE l.name=? AND c.book_number=?
               ORDER BY c.chapter_number""", (name, bk)).fetchall()
        q = f"List every scene set at {name} in book {bk}."
        item = make_item("lk", seq, q, "lookup", cids, cites, [name],
                         f"locations table: {name!r} tagged in {n} chunks of book {bk}")
        if item:
            items.append(item)
            per_book[bk] += 1
            seq += 1
    return items


# --------------------------------------------------------------------------
# general: from events (plot questions -> plain semantic search)
# --------------------------------------------------------------------------

def gen_general(con) -> list[dict]:
    # First tokens of known character names, used to preserve capitalization.
    _PROPER_FIRST.update(
        r[0].split()[0] for r in con.execute("SELECT name FROM character_profiles"))
    rows = con.execute(
        """SELECT id, book_number, chapter_number, title, type, summary,
                  source_chunk_ids_json
           FROM events
           WHERE type IN ('confrontation','revelation','discovery','death','loss')
             AND length(title) BETWEEN 25 AND 75
             AND source_chunk_ids_json IS NOT NULL
           ORDER BY book_number, id""").fetchall()
    items, seq = [], 1
    quota = Counter()
    for eid, bk, ch, title, etype, summary, cids_json in rows:
        if quota[bk] >= 4:
            continue
        cids = json.loads(cids_json or "[]")
        if not cids:
            continue
        # Lowercase the leading word only when it is not a proper noun.
        first = re.split(r"['\s]", title, maxsplit=1)[0]
        proper = (first in _PROPER_FIRST
                  or first in {"Mr", "Mrs", "Ms", "Dr", "Chief", "Principal", "Coach"})
        clause = title if proper else title[0].lower() + title[1:]
        q = f"What happens when {clause} in book {bk}?"
        item = make_item("gn", seq, q, "general", cids[:4], [(bk, ch)],
                         key_terms(summary or title),
                         f"derived from events id {eid} ({etype}): {title!r}")
        if item:
            items.append(item)
            quota[bk] += 1
            seq += 1
        if len(items) >= 20:
            break
    return items


# --------------------------------------------------------------------------
# verify mode
# --------------------------------------------------------------------------

def verify(path: Path) -> int:
    con = connect()
    known_chunks = {r[0] for r in con.execute("SELECT chunk_id FROM chunks")}
    known_cites = {(r[0], r[1]) for r in con.execute(
        "SELECT DISTINCT book_number, chapter_number FROM chunks")}
    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    counts: Counter = Counter()
    scopes: Counter = Counter()
    failures = []
    ids = set()
    for it in items:
        counts[it["qtype"]] += 1
        plan = classify(it["question"])
        if plan.qtype != it["qtype"]:
            failures.append(f"{it['id']}: classify() -> {plan.qtype}, expected {it['qtype']}")
        if scope_str(plan) != it["scope"]:
            failures.append(f"{it['id']}: classify() scope {scope_str(plan)!r} != recorded {it['scope']!r}")
        for cid in it["expected_chunk_ids"]:
            if cid not in known_chunks:
                failures.append(f"{it['id']}: unknown chunk_id {cid}")
        if not it["expected_citations"]:
            failures.append(f"{it['id']}: no expected_citations")
        for bk, ch in it["expected_citations"]:
            if (bk, ch) not in known_cites:
                failures.append(f"{it['id']}: citation [{bk},{ch}] not in corpus")
        if not it["answer_must_mention"]:
            failures.append(f"{it['id']}: empty answer_must_mention")
        if it["id"] in ids:
            failures.append(f"{it['id']}: duplicate id")
        ids.add(it["id"])
        scopes["series-wide" if it["scope"] is None else
               ("multi-book" if it["scope"].startswith("books:") else "single-book")] += 1
    print(f"Verified {path.name}: {len(items)} items")
    print(f"{'qtype':<20} {'count':>5}")
    print("-" * 26)
    for qt in ("temporal_knowledge", "sentiment", "continuity", "lookup", "general"):
        print(f"{qt:<20} {counts[qt]:>5}")
    print("-" * 26)
    print(f"{'total':<20} {len(items):>5}")
    print("scope mix:", dict(sorted(scopes.items())))
    alias = [it["id"] for it in items if "alias" in it.get("tags", [])]
    if alias:
        print(f"alias items ({len(alias)}):", ", ".join(alias))
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(" -", f)
        return 1
    print("\nAll checks passed: every question routes to its intended qtype;")
    print("all chunk ids and citations exist in the corpus.")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--verify":
        target = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "eval" / "golden_set.jsonl"
        return verify(target)

    con = connect()
    items = (gen_temporal(con) + gen_sentiment(con) + gen_continuity(con)
             + gen_lookup(con) + gen_general(con))
    with OUT_PATH.open("w") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    counts = Counter(it["qtype"] for it in items)
    print(f"Wrote {len(items)} candidates to {OUT_PATH}")
    for qt, n in sorted(counts.items()):
        print(f"  {qt:<20} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

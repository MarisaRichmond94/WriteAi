"""Build an UNBIASED, text-grounded golden eval set.

eval/build_golden_candidates.py derives questions FROM extracted metadata, so
it favours whichever extraction model produced that metadata — useless for
comparing extraction models. This generator grounds everything in the raw
chapter TEXT (identical across extraction models) using three strategies, one
per family of query type that src.query_router.classify() recognises:

  * temporal_knowledge / sentiment / continuity / general
      An independent author model (Opus 4.8 — neither model under test) reads a
      passage and writes questions whose answer is supported by THAT passage.
      classify() vocabulary differs per type, so the author is given phrasing
      templates; the item is then RELABELLED with classify()'s actual verdict
      (honest routing, not the author's guess) and kept if grounded.
      Continuity is framed as "what does this passage leave unresolved / set
      up" — the setup is on the page even though the payoff comes later.

  * lookup
      classify() routes lookup to enumeration ("every scene where X appears"),
      which is corpus-level, not single-passage. Ground truth is built by TEXT
      SEARCH: for a human-curated character name (writer_data/character_map.json,
      model-independent), the expected chunks are those whose text contains the
      name. Restricted to names with a small enough footprint to fit top_k.

Grounding gates (author path): supporting_chunk_ids ⊆ passage; every
answer_must_mention phrase is a verbatim substring of the cited chunk text.
Emitted in eval/golden_set.jsonl's schema so run_eval.py consumes it unchanged.

Usage (repo root):
    .venv/bin/python eval/build_golden_textgrounded.py --db <snapshot.sqlite>
    .venv/bin/python eval/build_golden_textgrounded.py --passages 2 --db ...   # smoke
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import load_config
from src.query_router import classify

QTYPES = ("temporal_knowledge", "sentiment", "continuity", "lookup", "general")
AUTHOR_MODEL = "claude-opus-4-8"          # independent of Haiku/Sonnet under test
PER_QTYPE_TARGET = 20
PASSAGES_PER_BOOK = 8
LOOKUP_MIN, LOOKUP_MAX = 3, 12            # name footprint that fits top_k=15

SYSTEM = """You are building a rigorous evaluation set for a retrieval system \
over a five-book fiction series. You are given the verbatim text of one passage \
(a chapter), narrated in first person and split into labelled chunks, plus the \
NARRATOR's name and pronouns (in the user message). Write questions whose \
answers are EXPLICITLY and FULLY supported by THIS passage alone.

GROUNDING (critical — violations make the item useless):
  - State ONLY what is explicitly on the page. Never infer, assume, or add \
specific details (causes, methods, outcomes, identities) not directly stated \
in this passage.
  - If a character only suspects / wonders / fears something, say "suspects" or \
"wonders" — do NOT phrase it as established knowledge or fact.
  - For temporal_knowledge, only attribute knowledge the narrator explicitly \
states, thinks, or is told IN THIS PASSAGE. Do not attribute knowledge of \
events or details the character could not plausibly know, even if the narration \
happens to mention them.

NAMING:
  - Refer to the narrator by the name given in the user message, with that \
character's correct pronouns. NEVER write "the narrator", "the protagonist", or \
a bare "they/them" for a known character.
  - Use each character's primary name, not a nickname another character uses.

Write questions of these kinds, using the phrasing shown (phrasing routes the \
question to the right retrieval path):
  - temporal_knowledge: "What does <Name> know about <X> ...?" / "aware of" / \
"learned" — knowledge shown in this passage.
  - sentiment: "How does <Name> feel about <X>?" / "What is the relationship \
between <A> and <B>?" — emotion/relationship depicted here.
  - continuity: "What unresolved question does this chapter raise about <X>?" / \
"What does this passage set up / foreshadow ...?" — the SETUP is on the page.
  - general: a plain plot/event question — "What happens when ...?"

For each question provide:
  - answer: 1-3 sentences, strictly from the passage, no inference.
  - supporting_chunk_ids: chunk id(s) shown in the passage that contain the \
answer (only ids from THIS passage).
  - answer_must_mention: 2-4 SHORT phrases copied VERBATIM (exact characters) \
from the cited chunk text — literal substrings, not paraphrases.

Prefer questions a real reader would ask. Skip a kind if the passage doesn't \
cleanly support it. Do NOT write enumeration/counting questions ("every scene", \
"how many chapters") — those are generated separately."""

# Pronouns for the known point-of-view characters (writer_data has no gender
# map). "Unknown" POV -> the author is told to name the narrator from the text.
POV_PRONOUNS = {
    "Jared Gatlin": "he/him", "Noah Gatlin": "he/him",
    "Chase Gatlin": "he/him", "Emma Mendoza": "she/her",
}

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "answer": {"type": "string"},
            "supporting_chunk_ids": {"type": "array", "items": {"type": "string"}},
            "answer_must_mention": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question", "answer", "supporting_chunk_ids", "answer_must_mention"],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}


def _passages(db, per_book):
    out = []
    for bnum, btitle in db.execute(
            "SELECT DISTINCT book_number, book_title FROM chunks ORDER BY book_number"):
        chapters = [r[0] for r in db.execute(
            "SELECT DISTINCT chapter_number FROM chunks WHERE book_number=? "
            "ORDER BY chapter_number", (bnum,))]
        step = max(1, len(chapters) // per_book)
        for ch in chapters[::step][:per_book]:
            rows = list(db.execute(
                "SELECT chunk_id, text, pov_character FROM chunks WHERE "
                "book_number=? AND chapter_number=? ORDER BY chunk_id", (bnum, ch)))
            if not rows:
                continue
            povs = [r[2] for r in rows if r[2] and r[2] != "Unknown"]
            pov = Counter(povs).most_common(1)[0][0] if povs else "Unknown"
            out.append({"book": bnum, "title": btitle, "chapter": ch, "pov": pov,
                        "chunks": [(r[0], r[1]) for r in rows],
                        "ids": {r[0] for r in rows}})
    return out


def _author(client, passage):
    body = "\n\n".join(f"=== CHUNK {cid} ===\n{t}" for cid, t in passage["chunks"])
    if passage["pov"] == "Unknown":
        narrator = "NARRATOR: identify the first-person narrator from the text " \
                   "and refer to them by name with correct pronouns."
    else:
        pron = POV_PRONOUNS.get(passage["pov"], "use the pronouns the text uses")
        narrator = f"NARRATOR: {passage['pov']} ({pron})."
    resp = client.messages.create(
        model=AUTHOR_MODEL, max_tokens=4000, system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content":
                   f"Book {passage['book']} ({passage['title']}), chapter "
                   f"{passage['chapter']}. {narrator}\n\nPassage:\n\n{body}"}])
    if resp.stop_reason == "refusal":
        return []
    txt = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    try:
        return json.loads(txt).get("items", [])
    except json.JSONDecodeError:
        return []


def _grounded(item, passage, chunk_text):
    ids = item.get("supporting_chunk_ids") or []
    if not ids or not set(ids) <= passage["ids"]:
        return False, "chunk ids not in passage"
    joined = "\n".join(chunk_text[c] for c in ids)
    phrases = item.get("answer_must_mention") or []
    if not phrases or not all(p in joined for p in phrases):
        return False, "anchor phrase not verbatim"
    return True, "ok"


def _cites(ids):
    return [list(c) for c in sorted({(int(c[1:3]), int(c[5:8])) for c in ids})]


# Titles / honorifics / kinship terms that are NOT names — never search on these
# (else "Chief", "Coach", "Mr." match every scene with that word).
_TITLES = {"mr", "mrs", "ms", "dr", "chief", "coach", "judge", "nurse", "officer",
           "principal", "professor", "señora", "senora", "sergeant", "captain",
           "detective", "sir", "madam", "grandpa", "grandma", "mom", "dad",
           "uncle", "aunt", "father", "mother", "señor", "senor"}


def _curated_names():
    """First names + full names of human-curated characters, EXCLUDING any name
    led by a title (Mr./Chief/Coach/...) — those produce title-word false matches."""
    m = json.loads((REPO_ROOT / "writer_data" / "character_map.json").read_text())
    full = set(m.get("relationship_overrides", {})) | set(m.get("photos", {}))
    names = set()
    for n in full:
        toks = n.split()
        if not toks or toks[0].strip(".").lower() in _TITLES:
            continue  # title-led (Mr. Park, Chief Mackenzie) — skip for name search
        names.add(n)          # full name
        names.add(toks[0])    # first name (text usually uses it)
    return {n for n in names
            if len(n) > 2 and n[0].isupper() and n.strip(".").lower() not in _TITLES}


def _lookup_items(db, per_book):
    """Text-search-grounded enumeration items: scenes where a named character
    appears, restricted to names with a small enough per-book footprint."""
    names = _curated_names()
    rows = list(db.execute("SELECT chunk_id, book_number, text FROM chunks"))
    out = []
    for bnum in sorted({r[1] for r in rows}):
        bchunks = [(cid, txt) for cid, b, txt in rows if b == bnum]
        made = 0
        for name in sorted(names):
            pat = re.compile(rf"\b{re.escape(name)}\b")
            hits = [cid for cid, txt in bchunks if pat.search(txt)]
            if LOOKUP_MIN <= len(hits) <= LOOKUP_MAX:
                # "mentioned", not "appears": ground truth is name-in-text, so the
                # question must ask exactly that (a mention IS a mention — avoids the
                # appears-vs-mentioned mismatch a reader would otherwise flag).
                q = f"In book {bnum}, list every scene where {name} is mentioned."
                if classify(q).qtype != "lookup":
                    continue
                out.append({
                    "question": q, "qtype": "lookup", "scope": f"book:{bnum}",
                    "expected_chunk_ids": sorted(hits),
                    "expected_citations": _cites(hits),
                    "answer": f"{name} is mentioned in {len(hits)} scene(s) in book {bnum}.",
                    "answer_must_mention": [name], "tags": [],
                    "notes": f"text-search grounded: chunks containing '{name}' in book {bnum}",
                })
                made += 1
                if made >= per_book:
                    break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passages", type=int, default=None)
    ap.add_argument("--out", default="eval/golden_textgrounded.jsonl")
    ap.add_argument("--per-qtype", type=int, default=PER_QTYPE_TARGET)
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    cfg = load_config()
    from anthropic import Anthropic
    client = Anthropic()
    db = sqlite3.connect(args.db or cfg.sqlite_path)
    chunk_text = dict(db.execute("SELECT chunk_id, text FROM chunks"))

    kept = defaultdict(list)
    rejected = Counter()

    # ── author path: tk / sn / continuity / general (relabelled by classify) ──
    passages = _passages(db, PASSAGES_PER_BOOK)
    if args.passages:
        passages = passages[:args.passages]
    print(f"authoring over {len(passages)} passages via {AUTHOR_MODEL}...")
    for i, p in enumerate(passages, 1):
        for item in _author(client, p):
            ok, why = _grounded(item, p, chunk_text)
            if not ok:
                rejected[why] += 1
                continue
            blob = (item["question"] + " " + item["answer"]).lower()
            if "narrator" in blob or "protagonist" in blob:
                rejected["still says 'narrator'/'protagonist'"] += 1
                continue
            qt = classify(item["question"]).qtype     # honest routing verdict
            if qt == "lookup":                          # author path never owns lookup
                rejected["authored routed to lookup"] += 1
                continue
            ids = sorted(item["supporting_chunk_ids"])
            kept[qt].append({
                "question": item["question"].strip(), "qtype": qt,
                "scope": f"book:{p['book']}", "expected_chunk_ids": ids,
                "expected_citations": _cites(ids), "answer": item["answer"].strip(),
                "answer_must_mention": item["answer_must_mention"], "tags": [],
                "notes": f"text-grounded from b{p['book']:02d} ch{p['chapter']} "
                         f"(author {AUTHOR_MODEL})",
            })
        print(f"  [{i}/{len(passages)}] {dict((k, len(v)) for k, v in kept.items())}")

    # ── lookup path: text-search grounded ──
    for it in _lookup_items(db, per_book=max(3, args.per_qtype // 4)):
        kept["lookup"].append(it)
    print(f"lookup (text-search): {len(kept['lookup'])}")

    # ── balance + write ── stratify each qtype's picks EVENLY across books,
    # round-robin, so no book is starved (passages process book-1-first, so a
    # naive head-slice over-weights early books and drops book 5 entirely).
    def _stratify(items, target):
        by_book = defaultdict(list)
        for it in items:
            by_book[it["scope"]].append(it)
        books = sorted(by_book)
        idx = {b: 0 for b in books}
        picked = []
        while len(picked) < target and any(idx[b] < len(by_book[b]) for b in books):
            for b in books:
                if idx[b] < len(by_book[b]):
                    picked.append(by_book[b][idx[b]])
                    idx[b] += 1
                    if len(picked) >= target:
                        break
        return picked

    pre = {"temporal_knowledge": "tk", "sentiment": "sn", "continuity": "ct",
           "lookup": "lk", "general": "gn"}
    out_items = []
    for qt in QTYPES:
        for n, it in enumerate(_stratify(kept[qt], args.per_qtype), 1):
            it["id"] = f"tg-{pre[qt]}-{n:03d}"
            out_items.append(it)
    out_path = REPO_ROOT / args.out
    with open(out_path, "w") as f:
        for it in out_items:
            f.write(json.dumps(it) + "\n")
    print(f"\nwrote {len(out_items)} -> {out_path}")
    print("per qtype:", {qt: min(len(kept[qt]), args.per_qtype) for qt in QTYPES})
    print("rejections:", dict(rejected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

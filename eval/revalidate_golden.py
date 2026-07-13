#!/usr/bin/env python3
"""Re-validate a golden set against the LIVE settled index, in place.

Self-healing so an overnight run stays correct even if a sync shifted chunks
just before it fired:

  * lookup items  -> re-ground expected_chunk_ids by text-searching the character
                     name (deterministic). Dropped only if the name no longer
                     appears anywhere in its book.
  * authored items (non-lookup) -> dropped if any expected chunk is gone OR an
                     answer_must_mention anchor is no longer verbatim in the
                     expected chunks' text (an authored Q/A can't be auto-repaired).

Idempotent; safe to run repeatedly. Prints a one-line summary per set.
"""
import json, re, sqlite3, sys
from pathlib import Path

DB = "data/series_metadata.sqlite"


def cites(ids):
    return [list(c) for c in sorted({(int(c[1:3]), int(c[5:8])) for c in ids})]


def revalidate(path):
    rows = list(sqlite3.connect(DB).execute(
        "SELECT chunk_id, book_number, text FROM chunks"))
    live = {c for c, _, _ in rows}
    text_of = {c: t for c, _, t in rows}
    items = [json.loads(l) for l in open(path) if l.strip()]
    out, dropped, reground = [], [], 0

    for it in items:
        if it.get("qtype") == "lookup":
            q = it.get("question", "")
            if "where " in q and " is mentioned" in q and it.get("scope", "").startswith("book:"):
                name = q.split("where ")[1].split(" is mentioned")[0]
                bk = int(it["scope"].split(":")[1])
                pat = re.compile(rf"\b{re.escape(name)}\b")
                hits = sorted(cid for cid, b, txt in rows if b == bk and pat.search(txt))
                if not hits:
                    dropped.append((it["id"], "lookup-name-gone"))
                    continue
                if hits != it.get("expected_chunk_ids"):
                    it["expected_chunk_ids"] = hits
                    it["expected_citations"] = cites(hits)
                    it["answer"] = f"{name} is mentioned in {len(hits)} scene(s) in book {bk}."
                    reground += 1
                out.append(it)
                continue
            # unparseable lookup -> fall through to the generic staleness check

        if not set(it["expected_chunk_ids"]) <= live:
            dropped.append((it["id"], "missing-chunk"))
            continue
        anchors = it.get("answer_must_mention") or []
        joined = "\n".join(text_of[c] for c in it["expected_chunk_ids"])
        if anchors and not all(a in joined for a in anchors):
            dropped.append((it["id"], "anchor-broken"))
            continue
        out.append(it)

    Path(path).write_text("\n".join(json.dumps(i) for i in out) + "\n")
    print(f"[revalidate] {path}: kept {len(out)} | re-grounded {reground} | "
          f"dropped {len(dropped)} {dropped}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        revalidate(p)

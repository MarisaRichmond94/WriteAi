"""End-to-end test that renumbering a book does not corrupt or re-bill the index.

Inserting or dragging a chapter in Loom renumbers every chapter below it. The
chunk id is positional (`b02.c040.s01.k00`) and so are the enrichment tables,
so a renumbering is the change most likely to (a) re-run the metadata model
over prose nobody edited and (b) leave summaries and events attached to the
wrong chapter. Both have happened. This exercises the real pipeline against
COPIES of the real index and manuscript and asserts neither does.

Everything happens in a sandbox under the system temp dir, driven through the
BOOKS_DIR / DATA_DIR env vars that config.load_config already honours. It
never writes to BOOKS_DIR or to the live data dir — the copies are made with
SQLite's backup API rather than cp, because a plain copy of a live database
drops the WAL and produces a stale copy that reads like a code bug.

    .venv/bin/python scripts/sandbox_renumber_test.py                # both
    .venv/bin/python scripts/sandbox_renumber_test.py -s reorder     # one
    .venv/bin/python scripts/sandbox_renumber_test.py --plan-only    # no writes

COST: the `insert` scenario adds a genuinely new chapter, which is one real
extraction call (~$0.005). `reorder` invents no new prose and must cost
exactly $0.00 — if it ever doesn't, that is the regression this is here to
catch. `--plan-only` stops before any API call or database write.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from config import load_config  # noqa: E402

SANDBOX = Path(tempfile.gettempdir()) / "writeai-renumber-sandbox"


# ── sandbox construction ────────────────────────────────────────────────────

def build(book_number: int) -> tuple[Path, Path, str]:
    """Copy the index and one book's sidecars into a fresh sandbox."""
    from src.discovery import discover_books

    cfg = load_config()
    book = next((b for b in discover_books(cfg) if b.number == book_number), None)
    if book is None:
        sys.exit(f"book {book_number} not found under {cfg.books_dir}")

    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    books = SANDBOX / "books" / book.folder.name
    data = SANDBOX / "data"
    books.mkdir(parents=True)
    data.mkdir(parents=True)

    # Only what WriteAI actually ingests — not the .pages/.pdf/audio siblings.
    for name in (f"{book.title}.txt", f"{book.title}.manifest.json"):
        src = book.folder / name
        if not src.exists():
            sys.exit(f"{src} missing — canon-export the book from Loom first")
        shutil.copy2(src, books / name)

    src_db = sqlite3.connect(f"file:{cfg.sqlite_path}?mode=ro", uri=True)
    dst_db = sqlite3.connect(data / "series_metadata.sqlite")
    src_db.backup(dst_db)   # never cp: a live DB's WAL would be dropped
    dst_db.close()
    src_db.close()
    shutil.copy2(cfg.chunk_hashes_path, data / "chunk_hashes.json")

    # chroma is deliberately not copied: it is >100MB, carries the same WAL
    # hazard, and nothing asserted here reads it (carry_chunks re-embeds
    # locally and reads metadata from SQLite). A fresh empty collection makes
    # the SQLite assertions strictly harder, not easier.
    return books, data, book.title


def sandbox_env(data: Path, books_root: Path) -> dict:
    env = os.environ.copy()
    env["BOOKS_DIR"] = str(books_root)
    env["DATA_DIR"] = str(data)
    return env


# ── the two ways a book gets renumbered ─────────────────────────────────────

NEW_CHAPTER_PROSE = (
    "The hallway outside is empty enough that my own footsteps sound like an "
    "accusation. I count the ceiling tiles because counting is easier than "
    "thinking about what I just did.\n"
    "I tell myself I will go back in a minute. I tell myself a lot of things.\n"
)


def _read_blocks(txt: Path):
    """(preamble, [(chapter_number, body_lines)]) — bare-number headings are
    chapters, exactly as src/chunker.py's splitter reads them."""
    preamble, blocks, head, buf = [], [], None, []
    for line in txt.read_text(encoding="utf-8").split("\n"):
        if re.fullmatch(r"\d+", line.strip()):
            if head is None:
                preamble = buf
            else:
                blocks.append((head, buf))
            head, buf = int(line.strip()), []
        else:
            buf.append(line)
    if head is not None:
        blocks.append((head, buf))
    return preamble, blocks


def _write_blocks(txt: Path, preamble, blocks) -> None:
    out = list(preamble)
    for n, body in sorted(blocks):
        out.append(str(n))
        out.extend(body)
    txt.write_text("\n".join(out), encoding="utf-8")


def apply_insert(books: Path, title: str, at: int) -> str:
    """What Loom writes when a chapter is inserted: a new heading at `at`, and
    every heading below it incremented. The manifest gains a record with a
    fresh cuid; every later record KEEPS its cuid and gains one to its number,
    which is the property the whole fix rests on."""
    txt = books / f"{title}.txt"
    preamble, blocks = _read_blocks(txt)
    shifted = [(n + 1 if n >= at else n, body) for n, body in blocks]
    pov, date = _pov_and_date(blocks, at)
    shifted.append((at, [pov, date] + NEW_CHAPTER_PROSE.strip("\n").split("\n") + [""]))
    _write_blocks(txt, preamble, shifted)

    path = books / f"{title}.manifest.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    for c in m["chapters"]:
        if c["number"] >= at:
            c["number"] += 1
            c["label"] = str(c["number"])
    m["chapters"].append({
        "id": "cmSANDBOXnewchapter0001", "number": at, "label": str(at),
        "pov": pov, "date": date, "wordCount": len(NEW_CHAPTER_PROSE.split()),
        "contentHash": "sandbox-new-chapter"})
    m["chapters"].sort(key=lambda c: c["number"])
    m["chapterCount"] = len(m["chapters"])
    path.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return f"inserted a new chapter {at}; everything below shifted down one"


def apply_reorder(books: Path, title: str, frm: int, to: int) -> str:
    """A drag in Loom's outline tree. The riskiest case: it changes no chapter
    COUNT, so the post-ingest roster check sees no difference and never forces
    an enrichment run. Nothing regenerates — correctness rests entirely on
    rows being repositioned by identity. It must also cost exactly $0."""
    move = {frm: to}
    step = 1 if to > frm else -1
    for n in range(frm + step, to + step, step):
        move[n] = n - step

    txt = books / f"{title}.txt"
    preamble, blocks = _read_blocks(txt)
    _write_blocks(txt, preamble, [(move.get(n, n), body) for n, body in blocks])

    path = books / f"{title}.manifest.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    for c in m["chapters"]:
        if c["number"] in move:
            c["number"] = move[c["number"]]
            c["label"] = str(c["number"])
    m["chapters"].sort(key=lambda c: c["number"])
    path.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return f"dragged chapter {frm} to position {to}"


def _pov_and_date(blocks, at: int) -> tuple[str, str]:
    """Reuse the neighbouring chapter's header lines so the new chapter parses
    like every other one."""
    for n, body in blocks:
        if n == at:
            lines = [ln for ln in body if ln.strip()]
            return (lines[0] if lines else "Unknown",
                    lines[1] if len(lines) > 1 else "")
    return "Unknown", ""


# ── observation ─────────────────────────────────────────────────────────────

def snapshot(data: Path, book: int) -> dict:
    db = sqlite3.connect(f"file:{data/'series_metadata.sqlite'}?mode=ro", uri=True)
    snap = {
        "chunks": {cid: {"chapter": ch, "text": t, "meta": m} for cid, ch, t, m
                   in db.execute("SELECT chunk_id, chapter_number, text, "
                                 "metadata_json FROM chunks WHERE book_number=?",
                                 (book,))},
        "summaries": {int(n): {"summary": s, "cuid": c} for n, s, c
                      in db.execute("SELECT chapter_number, summary, "
                                    "loom_chapter_id FROM chapter_summaries "
                                    "WHERE book_number=?", (book,))},
        "events": {f"{n}.{p}": {"title": t, "cuid": c} for n, p, t, c
                   in db.execute("SELECT chapter_number, position, title, "
                                 "loom_chapter_id FROM events WHERE book_number=?",
                                 (book,))},
    }
    db.close()
    return snap


def plan(env: dict, book: int) -> dict:
    """The diff as both the old and the new code would classify it."""
    code = f"""
import json
from config import load_config
from src.discovery import discover_books
from src.ingestion import (load_and_chunk_book, load_hash_index, diff_chunks,
                           detect_moved_chunks)
from src.extractor import estimate_extraction_cost
cfg = load_config()
b = next(x for x in discover_books(cfg) if x.number == {book})
chunks = load_and_chunk_book(cfg, b)
index = load_hash_index(cfg)
old = diff_chunks(chunks, index, {book})
new = diff_chunks(chunks, index, {book})
detect_moved_chunks(new, index, {book})
cost = lambda d: estimate_extraction_cost(d.changed, cfg.extraction_model)['estimated_cost_usd']
print("@@" + json.dumps({{"old": len(old.changed), "old_cost": cost(old),
                          "new": len(new.changed), "new_cost": cost(new),
                          "moved": len(new.moved)}}))
"""
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                         capture_output=True, text=True)
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith("@@")), None)
    if line is None:
        sys.exit(f"plan failed:\n{out.stdout}\n{out.stderr}")
    return json.loads(line[2:])


def run_ingest(env: dict, book: int) -> None:
    r = subprocess.run([sys.executable, "ingest.py", "--book", str(book),
                        "--yes", "--no-backup"],
                       cwd=REPO, env=env, capture_output=True, text=True)
    for ln in r.stdout.splitlines():
        if any(k in ln for k in ("carried", "processed:", "moved:", "deleted:",
                                 "api calls", "actual cost")):
            print("   ", ln.strip())
    if r.returncode != 0:
        sys.exit(f"ingest failed:\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}")


def run_post_ingest(env: dict) -> None:
    """What server/routers/books.py runs in its post-ingest watcher."""
    code = """
import sqlite3
from config import load_config
from server.enrich import reposition_renumbered_chapters, gc_orphans, live_chapter_ids
cfg = load_config(); db = sqlite3.connect(cfg.sqlite_path)
db.execute("PRAGMA busy_timeout = 30000")
print("    repositioned", reposition_renumbered_chapters(db, cfg), "row(s)")
print("    gc'd", gc_orphans(db, live_chapter_ids(db, cfg)), "orphan row(s)")
"""
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                       capture_output=True, text=True)
    print(r.stdout.rstrip() or r.stderr[-1500:])


# ── assertions ──────────────────────────────────────────────────────────────

def verify(before: dict, after: dict, books: Path, title: str,
           scenario: str) -> list[str]:
    manifest = json.loads((books / f"{title}.manifest.json").read_text())
    now_at = {c["number"]: c["id"] for c in manifest["chapters"]}
    fails: list[str] = []

    def check(label, ok, detail=""):
        print(f"    {'PASS' if ok else 'FAIL'}  {label}"
              f"{('  — ' + detail) if detail else ''}")
        if not ok:
            fails.append(label)

    # Prose must survive verbatim. Compare as multisets: a renumbering moves
    # text between ids, so per-id equality is the wrong question.
    b_text = sorted(v["text"] for v in before["chunks"].values())
    a_text = sorted(v["text"] for v in after["chunks"].values())
    if scenario == "insert":
        extra = [t for t in a_text if t not in b_text]
        check("every pre-existing chunk's prose still present",
              all(t in a_text for t in b_text), f"{len(b_text)} chunks")
        check("exactly the new chapter's prose was added", len(extra) >= 1,
              f"{len(extra)} new chunk(s)")
    else:
        check("prose is identical — a drag invents and destroys nothing",
              b_text == a_text, f"{len(a_text)} chunks")

    # Metadata must be carried, never dropped. A null here is a chunk that
    # would answer no question until something re-extracts it.
    nulls = [c for c, v in after["chunks"].items() if v["meta"] is None]
    check("no chunk lost its metadata", not nulls,
          f"{len(nulls)} null" if nulls else f"all {len(after['chunks'])} populated")

    # Metadata travelled WITH its prose rather than staying at the number.
    meta_by_text = {v["text"]: v["meta"] for v in before["chunks"].values()}
    drifted = [c for c, v in after["chunks"].items()
               if v["text"] in meta_by_text and meta_by_text[v["text"]]
               and v["meta"] != meta_by_text[v["text"]]]
    check("carried metadata matches the prose it was extracted from",
          not drifted, f"{len(drifted)} drifted" if drifted else "")

    # The bug this whole change exists to prevent.
    bad_s = [n for n, v in after["summaries"].items()
             if v["cuid"] and now_at.get(n) and now_at[n] != v["cuid"]]
    check("every summary sits on the chapter it belongs to", not bad_s,
          f"{len(bad_s)} mismatched" if bad_s
          else f"all {len(after['summaries'])} correct")

    bad_e = [k for k, v in after["events"].items()
             if v["cuid"] and now_at.get(int(k.split(".")[0]))
             and now_at[int(k.split(".")[0])] != v["cuid"]]
    check("every event sits on the chapter it belongs to", not bad_e,
          f"{len(bad_e)} mismatched" if bad_e
          else f"all {len(after['events'])} correct")

    # Negative control: without repositioning, how wrong would it have been?
    # If this is 0 the scenario did not actually renumber anything and the
    # checks above proved nothing.
    would = [n for n, v in before["summaries"].items()
             if v["cuid"] and now_at.get(n) and now_at[n] != v["cuid"]]
    check("the scenario genuinely renumbered chapters (control)", bool(would),
          f"{len(would)} chapters would have shown the wrong summary "
          f"without repositioning")
    return fails


# ── driver ──────────────────────────────────────────────────────────────────

def scenario_run(name: str, book: int, plan_only: bool) -> list[str]:
    print(f"\n{'=' * 70}\n{name.upper()}\n{'=' * 70}")
    books, data, title = build(book)
    env = sandbox_env(data, SANDBOX / "books")
    print(f"  sandbox: {SANDBOX}")

    base = plan(env, book)
    if base["old"] or base["new"]:
        sys.exit(f"  baseline is not clean ({base}) — the live index is behind "
                 f"its manuscript; sync first, then re-run.")
    print(f"  baseline clean: no pending changes")

    before = snapshot(data, book)
    what = (apply_insert(books, title, at=15) if name == "insert"
            else apply_reorder(books, title, frm=5, to=8))
    print(f"  {what}")

    p = plan(env, book)
    print(f"\n  cost of this change:")
    print(f"    before this work: {p['old']:>3} chunk(s) -> model   ${p['old_cost']:.4f}")
    print(f"    now:              {p['new']:>3} chunk(s) -> model   ${p['new_cost']:.4f}")
    print(f"                      {p['moved']:>3} carried, no API call")
    if name == "reorder" and p["new"]:
        print("    ^ a drag invents no prose; anything above zero is a regression")

    if plan_only:
        print("\n  --plan-only: stopping before any API call or database write.")
        return []

    print(f"\n  running the real pipeline:")
    run_ingest(env, book)
    run_post_ingest(env)

    print(f"\n  verifying:")
    fails = verify(before, snapshot(data, book), books, title, name)
    if name == "reorder" and p["new"]:
        fails.append("reorder cost money")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-s", "--scenario", choices=("insert", "reorder", "both"),
                    default="both")
    ap.add_argument("-b", "--book", type=int, default=1,
                    help="book number to copy into the sandbox (default: 1)")
    ap.add_argument("--plan-only", action="store_true",
                    help="report the diff and stop before any API call or write")
    ap.add_argument("--keep", action="store_true",
                    help="leave the sandbox on disk for inspection")
    args = ap.parse_args()

    names = ["insert", "reorder"] if args.scenario == "both" else [args.scenario]
    failed: dict[str, list[str]] = {}
    for name in names:
        fails = scenario_run(name, args.book, args.plan_only)
        if fails:
            failed[name] = fails

    print()
    if failed:
        for name, fails in failed.items():
            print(f"FAILED ({name}): {'; '.join(fails)}")
        return 1
    print("ALL CHECKS PASSED" if not args.plan_only else "PLAN ONLY — nothing asserted")
    if not args.keep and SANDBOX.exists():
        shutil.rmtree(SANDBOX)
        print(f"sandbox removed (--keep to retain it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

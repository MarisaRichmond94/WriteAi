"""Resolve each chapter's place on the series' internal calendar.

Chapter date lines ("Friday, December 4th") carry month and day but NO year,
and several books interleave two timelines (flashback chapters months before
the surrounding narrative). This script fills the `chapter_timeline` table so
that sorting chapters by (story_year, month, day) reproduces true STORY
chronology (used by GET /api/events?order=story behind ENABLE_STORY_ORDER):

  * month/day are parsed deterministically from the date line (never by the
    model); NULL when a chapter has no date line.
  * story_year — a small relative epoch consistent ACROSS books, NOT a real
    calendar year — plus temporal_mode/confidence/rationale come from ONE
    structured-output call per book to EXTRACTION_MODEL (cheap + fast),
    processing books sequentially and passing each book's resolved range
    forward so later books never restart the epoch count.
  * the model's story_year arithmetic is then VERIFIED and, where it violates
    calendar invariants, repaired deterministically (see repair_story_years):
    in practice the model is reliable about which chapters sit on an earlier/
    later timeline (the semantic judgment) but not about keeping the epoch
    bookkeeping consistent across 90-chapter books and book boundaries (it
    has incremented epochs at a November->December boundary, and given two
    same-school-year flashbacks different epochs). The repair keeps the
    model's temporal direction and recomputes only the year numbers, so the
    stored assignment always sorts consistently. Repaired rows get a note
    appended to their rationale.

Standalone by design: NOT part of the enrichment flow. Re-running is safe —
rows are upserted in place, and rows marked manual_override=1 are never
touched (fix a chapter by hand, set the flag, re-run freely).

Usage (from the repo root):
    .venv/bin/python scripts/resolve_chronology.py --dry-run   # plan, no API
    .venv/bin/python scripts/resolve_chronology.py             # resolve + upsert
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import load_config
from src.costlog import log_cost
from src.extractor import PRICING_PER_MTOK

log = logging.getLogger("resolve_chronology")

MAX_OUTPUT_TOKENS = 16000       # book 2 has 94 chapters; ~80 output tokens each
SUMMARY_CHARS = 280             # per-chapter summary budget in the prompt

_MONTHS = {m: i + 1 for i, m in enumerate([
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december"])}

_DATE_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\b\s+(\d{1,2})(?:st|nd|rd|th)?",
    re.IGNORECASE)


def parse_month_day(date_line: str | None) -> tuple[int | None, int | None]:
    """Deterministic month/day from a date line like "Friday, December 4th".
    The weekday is ignored on purpose: the dates are fictional and do not
    match any real calendar year."""
    if not date_line:
        return None, None
    m = _DATE_RE.search(date_line)
    if not m:
        return None, None
    day = int(m.group(2))
    return _MONTHS[m.group(1).lower()], (day if 1 <= day <= 31 else None)


SYSTEM_PROMPT = """You are placing the chapters of one book of a fiction series onto the series' internal calendar.

Chapter date lines give a weekday, month, and day — but NO year (the dates are fictional; ignore weekdays entirely). Some books interleave two timelines: flashback chapters set months before the surrounding narrative. Your job is to assign each chapter a story_year — a small relative CALENDAR-YEAR epoch (0, 1, 2, ...) shared across the entire series — such that sorting ALL chapters of the WHOLE series by the triple (story_year, month, day) reproduces the true in-story chronological order. The series starts at story_year 0.

story_year is a property of the chapter's DATE alone, exactly like a calendar year: it is NOT "which book" or "which timeline". Two chapters are in the same story_year if and only if no New Year (December 31 -> January 1) lies between their dates in story time.

Follow this procedure:

STEP 1 — true chronology. Using each chapter's month/day and summary, work out the true chronological order of the chapters. Chapters are listed in NARRATIVE order; flashback chapters happened EARLIER than the primary chapters around them (often months earlier, sometimes in the previous calendar year), flashforwards later.

STEP 2 — assign epochs by walking TRUE chronological order. Start from the epoch implied by the prior_books context (never restart at 0 for a later book). Each time the walk crosses a New Year — the month sequence passes from December into January — increment the epoch by exactly 1. Never increment anywhere else: a jump from May forward to September of the same calendar year keeps the SAME story_year.
- If this book's main timeline begins in a calendar month EARLIER than the month where the previous book's main timeline ended, a New Year has passed in between: the epoch increments.
- Flashbacks take the epoch of the calendar year their date falls in — which is often ONE LESS than the surrounding primary chapters' epoch (when the flashback is in Sep–Dec and the primary timeline is in Jan–Aug), and sometimes the SAME (no New Year in between).

STEP 3 — verify before answering. Mentally sort your assignments by (story_year, month, day) and check the result equals the true chronology from STEP 1. In particular: a flashback chapter must sort BEFORE the primary chapters it precedes in story time. If anything sorts wrong, fix the story_year values and re-check.

Worked example. A book's main timeline runs May 23 – July 22 of epoch E, with interleaved flashback chapters dated October 15, November 8, December 29, January 4, and February 9 set during the preceding school year. Then: the October, November and December flashbacks get story_year E-1; the January and February flashbacks get story_year E (New Year sits between December 29 and January 4); the May–July primary chapters keep story_year E. Sorted by (story_year, month, day) this yields Oct 15 -> Nov 8 -> Dec 29 -> Jan 4 -> Feb 9 -> May 23 -> ... -> Jul 22, the true story order.

temporal_mode per chapter:
- "primary": on the book's main narrative timeline.
- "flashback": set noticeably before the surrounding primary timeline.
- "flashforward": set noticeably after the surrounding primary timeline.
- "unknown": cannot tell.

Also give a confidence (0.0-1.0) and a one-line rationale per chapter. Return every chapter you were given, exactly once, keyed by its chapter_number."""

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"chapters": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "chapter_number": {"type": "integer"},
            "story_year": {"type": "integer"},
            "temporal_mode": {"type": "string", "enum": [
                "primary", "flashback", "flashforward", "unknown"]},
            "confidence": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": ["chapter_number", "story_year", "temporal_mode",
                     "confidence", "rationale"],
        "additionalProperties": False,
    }}},
    "required": ["chapters"],
    "additionalProperties": False,
}


def chapter_inputs(db: sqlite3.Connection) -> dict[int, list[dict]]:
    """Per-book chapter lists: chapter_number, date_line, parsed month/day,
    and a short summary (chapter_summaries, else first-chunk key_events)."""
    summaries = {(b, c): s for b, c, s in db.execute(
        "SELECT book_number, chapter_number, summary FROM chapter_summaries")}
    books: dict[int, list[dict]] = {}
    rows = db.execute(
        # bare columns resolve to the MIN(chunk_index) row (SQLite guarantee)
        """SELECT book_number, chapter_number, date_line, metadata_json,
                  MIN(chunk_index)
           FROM chunks
           GROUP BY book_number, chapter_number
           ORDER BY book_number, chapter_number""").fetchall()
    for book, ch, date_line, meta_json, _ in rows:
        summary = (summaries.get((book, ch)) or "").strip()
        if not summary and meta_json:  # fallback: first-chunk key events
            summary = "; ".join(json.loads(meta_json).get("key_events", [])[:4])
        month, day = parse_month_day(date_line)
        books.setdefault(book, []).append({
            "chapter_number": ch,
            "date_line": (date_line or "").strip() or None,
            "month": month,
            "day": day,
            "summary": summary[:SUMMARY_CHARS],
        })
    return books


def ensure_table(db: sqlite3.Connection) -> None:
    """Same DDL that src/storage.py ships (idempotent); inlined so this
    script never has to import the Chroma-backed SeriesStore."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS chapter_timeline (
            book_number     INTEGER NOT NULL,
            chapter_number  INTEGER NOT NULL,
            story_year      INTEGER NOT NULL,
            month           INTEGER,
            day             INTEGER,
            temporal_mode   TEXT NOT NULL DEFAULT 'primary',
            confidence      REAL,
            rationale       TEXT,
            manual_override INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (book_number, chapter_number)
        )""")
    db.commit()


def print_book_table(book: int, chapters: list[dict],
                     assigned: dict[int, dict] | None) -> None:
    print(f"\n── Book {book} "
          + ("(resolved)" if assigned else "(plan — no story_year yet)")
          + " " + "─" * 40)
    hdr = f"{'ch':>4}  {'date_line':<28} {'m/d':<6}"
    if assigned:
        hdr += f" {'year':>4}  {'mode':<12} {'conf':>4}"
    print(hdr)
    for c in chapters:
        md = (f"{c['month']}/{c['day']}"
              if c["month"] and c["day"] else "—")
        line = f"{c['chapter_number']:>4}  {(c['date_line'] or '—'):<28} {md:<6}"
        if assigned:
            a = assigned.get(c["chapter_number"])
            if a:
                line += (f" {a['story_year']:>4}  {a['temporal_mode']:<12}"
                         f" {a['confidence']:>4.2f}")
            else:
                line += "   (missing from model output)"
        print(line)


def resolve_book(client, cfg, book: int, chapters: list[dict],
                 prior_books: list[dict], usage: dict) -> dict[int, dict]:
    """One structured-output call for one book -> {chapter_number: assignment}.
    Chapters the model omitted inherit the previous chapter's story_year with
    temporal_mode 'unknown' (rare; keeps the table total)."""
    payload = {
        "book_number": book,
        "prior_books": prior_books,
        "chapters": chapters,
    }
    r = client.messages.create(
        model=cfg.extraction_model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema",
                                  "schema": _OUTPUT_SCHEMA}},
        messages=[{"role": "user",
                   "content": json.dumps(payload, ensure_ascii=False)}],
    )
    usage["input_tokens"] += r.usage.input_tokens
    usage["output_tokens"] += r.usage.output_tokens
    usage["api_calls"] += 1
    if r.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"chronology call ended with {r.stop_reason}")
    data = json.loads(next(b.text for b in r.content if b.type == "text"))

    valid = {c["chapter_number"] for c in chapters}
    assigned: dict[int, dict] = {}
    for item in data.get("chapters", []):
        ch = item.get("chapter_number")
        if ch in valid and ch not in assigned:
            item["confidence"] = min(1.0, max(0.0, float(item["confidence"])))
            assigned[ch] = item
    prev_year = None
    for c in chapters:  # narrative order — inherit forward
        ch = c["chapter_number"]
        if ch not in assigned:
            log.warning("book %d ch %d missing from model output; inheriting "
                        "story_year %s", book, ch, prev_year)
            assigned[ch] = {"chapter_number": ch,
                            "story_year": prev_year if prev_year is not None else 0,
                            "temporal_mode": "unknown", "confidence": 0.0,
                            "rationale": "model omitted this chapter; "
                                         "inherited previous chapter's epoch"}
        prev_year = assigned[ch]["story_year"]
    return assigned


# ── deterministic verification / repair ─────────────────────────────────────

def _main_thread(chapters: list[dict]) -> list[int]:
    """Indices (into `chapters`, narrative order) of the book's main timeline:
    the longest non-decreasing run of (month, day) among dated chapters.
    Interleaved flashback/flashforward chapters fall off this thread by
    construction. Limitation (fine for this series): a main timeline that
    itself crossed New Year mid-book would also split; none does."""
    idxs = [i for i, c in enumerate(chapters) if c["month"] and c["day"]]
    if not idxs:
        return []
    md = {i: (chapters[i]["month"], chapters[i]["day"]) for i in idxs}
    best: list[list[int]] = []  # best[k] = LIS ending at idxs[k]
    for k, i in enumerate(idxs):
        prev = max((best[j] for j in range(k) if md[idxs[j]] <= md[i]),
                   key=len, default=[])
        best.append(prev + [i])
    return max(best, key=len)


def repair_story_years(chapters: list[dict], assigned: dict[int, dict],
                       anchor: tuple[tuple[int, int], int] | None,
                       ) -> tuple[tuple[tuple[int, int], int] | None, int]:
    """Verify the model's epoch arithmetic against calendar invariants and fix
    in place where it is inconsistent; the model's temporal DIRECTION per
    chapter (flashback vs flashforward) is kept — only the year numbers (and
    a demonstrably-off-thread 'primary' label) are corrected.

    Invariants enforced:
      * every chapter on the book's main timeline shares one epoch E_main;
      * E_main continues the previous book's epoch (`anchor` = the previous
        book's last main-thread (month, day) + its epoch), incrementing by 1
        exactly when this book's main timeline starts at an EARLIER calendar
        date — i.e. a New Year passed between the books;
      * an off-thread chapter sits in the nearest epoch compatible with its
        direction: a flashback in the most recent past (same epoch when its
        date precedes the resumption point, else one year back), a
        flashforward in the nearest future.
    Undated chapters inherit the epoch of the nearest dated chapter.
    Returns (anchor for the next book, number of chapters changed)."""
    main = _main_thread(chapters)
    if not main:
        return anchor, 0
    md = lambda i: (chapters[i]["month"], chapters[i]["day"])
    e_main = 0
    if anchor is not None:
        prev_md, prev_epoch = anchor
        e_main = prev_epoch + (1 if md(main[0]) < prev_md else 0)

    main_set = set(main)
    changed = 0

    def put(i: int, year: int, mode: str | None = None) -> None:
        nonlocal changed
        a = assigned[chapters[i]["chapter_number"]]
        notes = []
        if a["story_year"] != year:
            notes.append(f"story_year {a['story_year']}->{year}")
            a["story_year"] = year
        if mode and a["temporal_mode"] != mode:
            notes.append(f"temporal_mode {a['temporal_mode']}->{mode}")
            a["temporal_mode"] = mode
        if notes:
            changed += 1
            a["rationale"] += f" [{'; '.join(notes)}: calendar consistency repair]"

    for i in main:
        put(i, e_main)
    for i, c in enumerate(chapters):
        if i in main_set or not (c["month"] and c["day"]):
            continue
        # resumption point: the next main-thread chapter, else the last one
        ref = next((j for j in main if j > i), main[-1])
        a = assigned[c["chapter_number"]]
        if a["temporal_mode"] == "flashforward":
            put(i, e_main + (0 if md(i) >= md(ref) else 1))
        else:  # flashback / unknown / mislabeled primary: nearest past
            put(i, e_main - (0 if md(i) <= md(ref) else 1),
                mode=("flashback" if a["temporal_mode"] == "primary" else None))
    for i, c in enumerate(chapters):  # undated: inherit from nearest dated
        if c["month"] and c["day"]:
            continue
        near = next((j for j in list(range(i + 1, len(chapters)))
                     + list(range(i - 1, -1, -1))
                     if chapters[j]["month"] and chapters[j]["day"]), None)
        if near is not None:
            put(i, assigned[chapters[near]["chapter_number"]]["story_year"])
    return (md(main[-1]), e_main), changed


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Assign story_year/temporal_mode to every chapter")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan (chapters, parsed dates, prompt "
                         "inputs) without any API calls or writes")
    args = ap.parse_args()

    cfg = load_config()
    db = sqlite3.connect(cfg.sqlite_path)
    ensure_table(db)
    books = chapter_inputs(db)
    if not books:
        print("no chapters found — ingest first")
        return 1

    overridden = {(b, c) for b, c in db.execute(
        "SELECT book_number, chapter_number FROM chapter_timeline "
        "WHERE manual_override = 1")}
    if overridden:
        print(f"respecting {len(overridden)} manual override(s); "
              "those rows will not be rewritten")

    if args.dry_run:
        for book in sorted(books):
            print_book_table(book, books[book], assigned=None)
        n = sum(len(v) for v in books.values())
        print(f"\ndry run: {n} chapters across {len(books)} book(s); "
              f"{len(books)} {cfg.extraction_model} call(s) would be made.")
        return 0

    import anthropic
    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key or None,
                                 max_retries=4)
    in_p, out_p = PRICING_PER_MTOK.get(cfg.extraction_model, (1.0, 5.0))
    usage = {"input_tokens": 0, "output_tokens": 0, "api_calls": 0}
    t0 = time.monotonic()

    prior_books: list[dict] = []   # running context passed forward
    anchor = None                  # (last main-thread (month, day), epoch)
    upserts = 0
    try:
        for book in sorted(books):
            chapters = books[book]
            assigned = resolve_book(client, cfg, book, chapters,
                                    prior_books, usage)
            anchor, n_fixed = repair_story_years(chapters, assigned, anchor)
            if n_fixed:
                print(f"book {book}: calendar consistency repair adjusted "
                      f"{n_fixed} chapter(s) (see rationale notes)")
            for c in chapters:
                a = assigned[c["chapter_number"]]
                if (book, c["chapter_number"]) in overridden:
                    continue  # belt and braces; the WHERE below also guards
                db.execute(
                    """INSERT INTO chapter_timeline
                           (book_number, chapter_number, story_year, month,
                            day, temporal_mode, confidence, rationale)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(book_number, chapter_number) DO UPDATE SET
                           story_year = excluded.story_year,
                           month = excluded.month,
                           day = excluded.day,
                           temporal_mode = excluded.temporal_mode,
                           confidence = excluded.confidence,
                           rationale = excluded.rationale
                       WHERE chapter_timeline.manual_override = 0""",
                    (book, c["chapter_number"], a["story_year"], c["month"],
                     c["day"], a["temporal_mode"], a["confidence"],
                     a["rationale"]))
                upserts += 1
            db.commit()
            print_book_table(book, chapters, assigned)
            years = [assigned[c["chapter_number"]]["story_year"]
                     for c in chapters]
            primary = [c for c in chapters
                       if assigned[c["chapter_number"]]["temporal_mode"]
                       == "primary"]
            prior_books.append({
                "book_number": book,
                "first_date_line": chapters[0]["date_line"],
                "last_date_line": chapters[-1]["date_line"],
                "story_year_min": min(years),
                "story_year_max": max(years),
                "last_primary_chapter": {
                    "date_line": primary[-1]["date_line"],
                    "story_year": assigned[
                        primary[-1]["chapter_number"]]["story_year"],
                } if primary else None,
            })
    finally:
        cost = round((usage["input_tokens"] * in_p
                      + usage["output_tokens"] * out_p) / 1e6, 4)
        if usage["api_calls"]:
            log_cost(cfg, surface="chronology", model=cfg.extraction_model,
                     usage=usage, cost_usd=cost,
                     latency_ms=int((time.monotonic() - t0) * 1000),
                     extra={"api_calls": usage["api_calls"],
                            "chapters_upserted": upserts})
        print(f"\n{usage['api_calls']} API call(s), "
              f"{usage['input_tokens']} in / {usage['output_tokens']} out "
              f"tokens — ${cost:.4f}; {upserts} chapter rows upserted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

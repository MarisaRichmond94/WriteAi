"""Books pane + chapter text + ingestion control (cost-gated)."""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config import REPO_ROOT

from .. import audit, writer_store
from ..deps import get_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_ingest = {"proc": None, "log_path": None, "started_at": None,
           "post_processing": False}
_ingest_lock = threading.Lock()


@router.get("/books")
def list_books():
    s = get_state()
    books = []
    rows = s.db.execute(
        """SELECT book_number, book_title,
                  COUNT(DISTINCT chapter_number), COUNT(*), SUM(word_count)
           FROM chunks GROUP BY book_number ORDER BY book_number""").fetchall()
    for num, title, chapters, chunks, words in rows:
        povs = [r[0] for r in s.db.execute(
            "SELECT DISTINCT pov_character FROM chunks WHERE book_number = ? "
            "AND pov_character IS NOT NULL ORDER BY pov_character", (num,))]
        chapter_rows = s.db.execute(
            """SELECT chapter_number, chapter_kind, pov_character, date_line,
                      SUM(word_count), COUNT(*)
               FROM chunks WHERE book_number = ?
               GROUP BY chapter_number ORDER BY chapter_number""", (num,)).fetchall()
        stats = {}
        for label, table in (("characters", "characters"), ("locations", "locations"),
                             ("knowledge_facts", "character_knowledge"),
                             ("foreshadowing", "foreshadowing"),
                             ("open_questions", "unresolved_questions")):
            stats[label] = s.db.execute(
                f"""SELECT COUNT(*) FROM {table} t JOIN chunks c
                    ON c.chunk_id = t.chunk_id WHERE c.book_number = ?""",
                (num,)).fetchone()[0]
        stats["events"] = s.db.execute(
            "SELECT COUNT(*) FROM events WHERE book_number = ?", (num,)).fetchone()[0] \
            if _has_events(s) else 0
        books.append({
            "id": num, "name": title, "chapter_count": chapters,
            "chunk_count": chunks, "word_count": words, "povs": povs,
            "stats": stats,
            "chapters": [{"chapter": c, "kind": k, "pov": p, "date": d,
                          "word_count": w, "chunk_count": n}
                         for c, k, p, d, w, n in chapter_rows],
        })
    hashes = get_state().cfg.chunk_hashes_path
    last_synced = (datetime.fromtimestamp(hashes.stat().st_mtime).isoformat()
                   if hashes.exists() else None)
    return {"books": books, "last_synced": last_synced}


def _has_events(s) -> bool:
    return s.db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='events'").fetchone() is not None


@router.get("/books/{book}/chapters/{chapter}/text")
def chapter_text(book: int, chapter: int):
    """Reconstruct a full chapter from its ordered chunks. When the ingest's
    rich-text sidecar exists (formatting-preserving paragraphs), attach it —
    viewers prefer it and fall back to the plain text."""
    s = get_state()
    rows = s.db.execute(
        """SELECT text, pov_character, date_line FROM chunks
           WHERE book_number = ? AND chapter_number = ?
           ORDER BY chunk_index""", (book, chapter)).fetchall()
    if not rows:
        raise HTTPException(404, "chapter not found")
    rich = None
    rich_path = s.cfg.rich_text_dir / f"book_{book}" / f"chapter_{chapter}.json"
    if rich_path.exists():
        try:
            rich = json.loads(rich_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            rich = None
    return {"book": book, "chapter": chapter,
            "pov": rows[0][1], "date": rows[0][2],
            "text": "\n\n".join(r[0] for r in rows),
            "rich": rich}


@router.get("/books/{book}/chapters/{chapter}/draft")
def chapter_draft(book: int, chapter: int):
    """Chapter text straight from the CURRENT manuscript file — staged copy,
    content-hash cached, zero LLM cost. Review-a-draft mode reads this
    instead of the index so the writer can iterate on a chapter without
    paying to re-ingest between rounds; the rich-formatting sidecar is
    extracted the same way. `in_sync` reports whether the index already
    matches this text (drives the "Draft — not indexed" badge)."""
    from src.chunker import split_into_segments
    from src.discovery import discover_books
    from src.parser import extract_text
    from src.richtext import extract_rich_paragraphs, split_rich_chapters

    s = get_state()
    b = next((x for x in discover_books(s.cfg) if x.number == book), None)
    if b is None:
        raise HTTPException(404, "book not found on disk")
    text, method = extract_text(b.manuscript, s.cfg)
    if text is None:
        raise HTTPException(502, "text extraction failed — see the server log")
    seg = next((x for x in split_into_segments(text)
                if x.kind != "part" and (x.chapter_number or 0) == chapter), None)
    if seg is None or not seg.paragraphs:
        raise HTTPException(404, "chapter not found in the manuscript file")
    draft_text = "\n\n".join(seg.paragraphs)

    rich = None
    try:
        paragraphs = extract_rich_paragraphs(b.manuscript, s.cfg)
        if paragraphs:
            rich = split_rich_chapters(paragraphs).get(chapter)
    except Exception:  # formatting is polish — never fail the draft read
        log.warning("rich extraction failed for draft b%s ch%s", book, chapter,
                    exc_info=True)

    rows = s.db.execute(
        """SELECT text FROM chunks WHERE book_number = ? AND chapter_number = ?
           ORDER BY chunk_index""", (book, chapter)).fetchall()

    def norm(t: str) -> str:
        return "\n".join(l for l in (ln.strip() for ln in t.split("\n")) if l)

    in_sync = bool(rows) and norm("\n\n".join(r[0] for r in rows)) == norm(draft_text)
    audit.log_event("draft_read", f"draft served for book {book} ch {chapter}",
                    method=method, in_sync=in_sync)
    return {"book": book, "chapter": chapter, "pov": seg.pov,
            "date": seg.date_line, "text": draft_text, "rich": rich,
            "in_sync": in_sync}


def _book_summary_dict(s, book: int) -> dict:
    dates = s.db.execute(
        """SELECT date_line FROM chunks WHERE book_number = ? AND date_line IS NOT NULL
           ORDER BY chapter_number, chunk_index""", (book,)).fetchall()
    povs = s.db.execute(
        """SELECT pov_character, COUNT(DISTINCT chapter_number) FROM chunks
           WHERE book_number = ? AND pov_character IS NOT NULL
           GROUP BY pov_character ORDER BY 2 DESC""", (book,)).fetchall()
    count = lambda table: s.db.execute(  # noqa: E731
        f"""SELECT COUNT(*) FROM {table} t JOIN chunks c ON c.chunk_id = t.chunk_id
            WHERE c.book_number = ?""", (book,)).fetchone()[0]
    has_events = s.db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name='events'").fetchone() is not None
    event_count = s.db.execute("SELECT COUNT(*) FROM events WHERE book_number = ?",
                               (book,)).fetchone()[0] if has_events else 0
    characters = s.db.execute(
        """SELECT COUNT(DISTINCT name) FROM characters ch
           JOIN chunks c ON c.chunk_id = ch.chunk_id WHERE c.book_number = ?""",
        (book,)).fetchone()[0]
    locations = s.db.execute(
        """SELECT COUNT(DISTINCT name) FROM locations l
           JOIN chunks c ON c.chunk_id = l.chunk_id WHERE c.book_number = ?""",
        (book,)).fetchone()[0]
    return {
        "date_span": {"first": dates[0][0] if dates else None,
                      "last": dates[-1][0] if dates else None},
        "pov_breakdown": [{"pov": p, "chapter_count": n} for p, n in povs],
        "character_count": characters,
        "location_count": locations,
        "event_count": event_count,
        "fact_count": count("character_knowledge"),
    }


@router.get("/books/{book}/summary")
def book_summary(book: int):
    return _book_summary_dict(get_state(), book)


@router.get("/series/summary")
def series_summary():
    s = get_state()
    books = [r[0] for r in s.db.execute(
        "SELECT DISTINCT book_number FROM chunks ORDER BY book_number")]
    titles = dict(s.db.execute("SELECT DISTINCT book_number, book_title FROM chunks"))
    has_events = s.db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name='events'").fetchone() is not None
    breakdown = []
    for b in books:
        chapters = s.db.execute(
            "SELECT COUNT(DISTINCT chapter_number) FROM chunks WHERE book_number = ?",
            (b,)).fetchone()[0]
        events = s.db.execute("SELECT COUNT(*) FROM events WHERE book_number = ?",
                              (b,)).fetchone()[0] if has_events else 0
        breakdown.append({"book": titles.get(b, f"Book {b}"),
                          "chapter_count": chapters, "event_count": events})
    # series-wide aggregate: reuse the per-book helper across all books
    agg = {"date_span": {"first": None, "last": None}, "pov_breakdown": [],
           "character_count": 0, "location_count": 0, "event_count": 0,
           "fact_count": 0}
    for b in books:
        one = _book_summary_dict(s, b)
        agg["event_count"] += one["event_count"]
        agg["fact_count"] += one["fact_count"]
        agg["character_count"] = max(agg["character_count"], one["character_count"])
        agg["location_count"] += one["location_count"]
        if agg["date_span"]["first"] is None:
            agg["date_span"]["first"] = one["date_span"]["first"]
        if one["date_span"]["last"]:
            agg["date_span"]["last"] = one["date_span"]["last"]
    agg["book_breakdown"] = breakdown
    return agg


@router.get("/books/{book}/chapters/{chapter}/extracted")
def chapter_extracted(book: int, chapter: int):
    """ExtractedChapter view assembled from stored chunk metadata."""
    s = get_state()
    rows = s.db.execute(
        """SELECT pov_character, date_line, metadata_json FROM chunks
           WHERE book_number = ? AND chapter_number = ? ORDER BY chunk_index""",
        (book, chapter)).fetchall()
    if not rows:
        raise HTTPException(404, "chapter not found")
    # collapse raw extraction tags ("Jared", "Emma") onto canonical names so
    # each character appears once under their full name
    s.canon.ensure_built()
    first_token: dict[str, list[str]] = {}
    for e in s.canon.entities.values():
        if e.kind == "character":
            first_token.setdefault(e.name.split()[0], []).append(e.name)

    def canonical(n: str) -> str:
        resolved = s.canon.resolve(n)
        if resolved:
            return resolved
        # quarantined-as-ambiguous bare names ("Jared"): safe to collapse
        # when exactly one character starts with that token
        matches = first_token.get(n)
        return matches[0] if matches and len(matches) == 1 else n

    summary, characters, facts, locations = [], {}, [], set()
    for pov, date, meta_json in rows:
        if not meta_json:
            continue
        meta = json.loads(meta_json)
        summary.extend(meta.get("key_events", []))
        for name in meta.get("characters_present", []):
            cn = canonical(name)
            characters.setdefault(cn, {"name": cn, "aliases": None,
                                       "role": "", "knowledge_gained": []})
        for who, learned in meta.get("character_knowledge_updates", {}).items():
            cn = canonical(who)
            entry = characters.setdefault(cn, {"name": cn, "aliases": None,
                                               "role": "", "knowledge_gained": []})
            entry["knowledge_gained"].extend(
                {"insight": fact, "source_quote": None} for fact in learned)
        facts.extend({"statement": f, "characters": [], "category": "revealed",
                      "source_quote": None}
                     for f in meta.get("new_information_revealed", []))
        locations.update(meta.get("locations", []))
    try:
        srow = s.db.execute(
            "SELECT summary FROM chapter_summaries WHERE book_number = ? "
            "AND chapter_number = ?", (book, chapter)).fetchone()
    except sqlite3.OperationalError:
        srow = None
    return {
        "chapter": chapter,
        "pov": rows[0][0] or "",
        "date": rows[0][1],
        "summary": summary[:10],
        "summary_text": srow[0] if srow else None,
        "characters": list(characters.values()),
        "events": [],
        "facts": facts[:20],
        "locations": [{"name": n, "type": ""} for n in sorted(locations)][:15],
    }


def _ch_label(n: int) -> str:
    return "Prologue" if n == 0 else f"Chapter {n}"


def _build_bible(s, book: int, compact: bool = False) -> tuple[str, str]:
    """(title, markdown). Assembled entirely from extracted/enriched data —
    deterministic, zero LLM cost, nothing invented.

    compact=True produces the trimmed variant injected into Explore chat
    context: no overview, characters capped at the POVs + most frequent
    (max 10), chapter prose summaries without the per-event bullets."""
    db = s.db
    row = db.execute("SELECT DISTINCT book_title FROM chunks WHERE book_number = ?",
                     (book,)).fetchone()
    if row is None:
        raise HTTPException(404, "book not found")
    title = row[0]
    canon = s.canon
    canon.ensure_built()
    cmap = writer_store.character_map()
    hidden = set(cmap.get("hidden", []))
    rel_overrides = cmap.get("relationship_overrides", {})
    genders = cmap.get("gender", {})

    # chapter skeleton: POV + date line from each chapter's first chunk
    ch_meta: dict[int, dict] = {}
    for ch, mj in db.execute(
            "SELECT chapter_number, metadata_json FROM chunks WHERE book_number = ? "
            "ORDER BY chapter_number, chunk_index", (book,)):
        if ch not in ch_meta:
            m = json.loads(mj or "{}")
            ch_meta[ch] = {"pov": m.get("pov_character"), "date": m.get("date_line")}

    # enriched events per chapter (skip gracefully if enrichment hasn't run)
    events_by_ch: dict[int, list] = defaultdict(list)
    try:
        for ch, t, typ, gran, summ in db.execute(
                "SELECT chapter_number, title, type, granularity, summary FROM events "
                "WHERE book_number = ? ORDER BY chapter_number, position", (book,)):
            events_by_ch[ch].append((t, typ, gran, summ))
    except sqlite3.OperationalError:
        pass

    # characters appearing in this book (canonical, user merges/hides applied)
    in_book: list[tuple[int, object]] = []
    for e in canon.entities.values():
        if e.kind != "character" or e.name in hidden:
            continue
        n = sum(1 for cid in e.chunk_ids
                if canon.chunk_meta.get(cid, (None,))[0] == book)
        if n:
            in_book.append((n, e))
    in_book.sort(key=lambda t: (-t[0], t[1].name))
    names_in_book = {e.name for _, e in in_book}

    profiles = {name: (tj, rj, aj) for name, tj, rj, aj in db.execute(
        "SELECT name, traits_json, relationships_json, arcs_json "
        "FROM character_profiles")}

    pov_counts: dict[str, int] = defaultdict(int)
    for meta in ch_meta.values():
        if meta["pov"]:
            pov_counts[meta["pov"]] += 1

    md: list[str] = []
    out = md.append
    out(f"# Story Bible — Book {book}: {title}")
    out("")
    chs = sorted(ch_meta)
    if not compact:
        out("> Generated by WriteAi from the manuscript text and its extracted "
            "metadata. Every fact below derives from the book itself — nothing is "
            "invented. Intended as reference context for drafting and rewriting.")
        out("")
        out("## Overview")
        out(f"- **Chapters:** {len(chs)}"
            + (" (Prologue + " + str(len(chs) - 1) + ")" if 0 in ch_meta else ""))
        if pov_counts:
            povs = ", ".join(f"{n} ({c} ch)" for n, c in
                             sorted(pov_counts.items(), key=lambda t: -t[1]))
            out(f"- **POV characters:** {povs}")
        dates = [m["date"] for m in ch_meta.values() if m["date"]]
        if dates:
            out(f"- **Timeline:** {dates[0]} → {dates[-1]}")
        out("")

    out("## Characters")
    out("")
    major = [(n, e) for n, e in in_book if n >= 3]
    if compact:
        # POVs always make the cut; fill the rest by appearance count
        major = ([(n, e) for n, e in major if e.name in pov_counts]
                 + [(n, e) for n, e in major if e.name not in pov_counts])[:10]
        major.sort(key=lambda t: (-t[0], t[1].name))
    for n, e in major:
        out(f"### {e.name}")
        tags = []
        if e.aliases:
            tags.append("aka " + ", ".join(e.aliases))
        if genders.get(e.name):
            tags.append(genders[e.name])
        if tags:
            out(f"*{' · '.join(tags)}*")
        tj, rj, aj = profiles.get(e.name, (None, None, None))
        traits = json.loads(tj) if tj else []
        if traits:
            out(f"- **Traits:** {', '.join(traits)}")
        arcs = json.loads(aj) if aj else {}
        if arcs.get(str(book)):
            out(f"- **Arc in this book:** {arcs[str(book)]}")
        rels = json.loads(rj) if rj else []
        rel_lines = []
        for r in rels:
            other = canon.resolve(r.get("name", "")) or r.get("name", "")
            if other not in names_in_book or other == e.name:
                continue
            nature = rel_overrides.get(e.name, {}).get(other) or r.get("nature")
            rel_lines.append(f"{other} ({nature})" if nature else other)
        if rel_lines:
            out(f"- **Relationships:** {'; '.join(rel_lines)}")
        out("")

    try:
        ch_prose = dict(db.execute(
            "SELECT chapter_number, summary FROM chapter_summaries "
            "WHERE book_number = ?", (book,)))
    except sqlite3.OperationalError:
        ch_prose = {}
    out("## Chapter-by-Chapter")
    out("")
    for ch in chs:
        meta = ch_meta[ch]
        head = f"### {_ch_label(ch)}"
        if meta["pov"]:
            head += f" — POV {meta['pov']}"
        if meta["date"]:
            head += f" — {meta['date']}"
        out(head)
        if ch in ch_prose:
            out(ch_prose[ch])
            out("")
        if compact:
            continue
        evs = events_by_ch.get(ch, [])
        if evs:
            for t, typ, gran, summ in evs:
                if gran == "minor":
                    out(f"- {t} *({typ})*")
                else:
                    out(f"- **{t}** *({typ})* — {summ}")
        else:
            out("- *(no extracted events)*")
        out("")

    return title, "\n".join(md)


@router.get("/books/{book}/bible")
def story_bible(book: int):
    """Downloadable per-book story bible (markdown), assembled from the
    extraction + enrichment layers. No LLM call — deterministic and free."""
    from fastapi.responses import Response

    s = get_state()
    title, md = _build_bible(s, book)
    slug = "-".join("".join(c if c.isalnum() else " " for c in title.lower()).split())
    return Response(
        md, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="story-bible-{book:02d}-{slug}.md"'})


# A user-uploaded cover lives here and overrides the auto-detected dust jacket.
# writer_data/ is the user's own decisions — never touched by AI or ingest.
COVERS_DIR = writer_store.WRITER_DATA_DIR / "covers"


def book_slug(title: str) -> str:
    """Slugify a book title the same way the frontend's bookSlug() does."""
    s = "".join(ch if ch.isalnum() else "-" for ch in title.lower())
    return "-".join(part for part in s.split("-") if part)


def manual_cover_path(slug: str) -> Path | None:
    """The user's uploaded override for a book, if any (by slug)."""
    if not COVERS_DIR.exists():
        return None
    for path in sorted(COVERS_DIR.glob(f"{slug}.*")):
        if path.is_file():
            return path
    return None


@router.get("/books/{book}/cover")
def book_cover(book: int):
    """Serve a book's cover: the user's manual upload if present, else the
    auto-detected dust-jacket cover (read-only)."""
    from fastapi.responses import FileResponse

    from src.discovery import discover_books
    s = get_state()
    match = next((b for b in discover_books(s.cfg) if b.number == book), None)
    if match is None:
        raise HTTPException(404, "unknown book")
    manual = manual_cover_path(book_slug(match.title))
    if manual is not None:
        # user-editable, so don't let the browser pin a stale copy
        return FileResponse(manual, headers={"Cache-Control": "no-cache"})
    for candidate in ("Dust Jacket/Front Cover.png", "Dust Jacket/Front Cover.jpg",
                      "cover.png", "cover.jpg"):
        path = match.folder / candidate
        if path.exists():
            # covers are print-resolution files; let the browser cache them
            return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(404, "no cover")


@router.get("/chunks/{chunk_id}")
def chunk_text(chunk_id: str):
    s = get_state()
    row = s.db.execute(
        """SELECT text, book_number, book_title, chapter_number, pov_character,
                  date_line FROM chunks WHERE chunk_id = ?""", (chunk_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "chunk not found")
    return {"chunk_id": chunk_id, "text": row[0], "book_number": row[1],
            "book_title": row[2], "chapter_number": row[3],
            "pov_character": row[4], "date_line": row[5]}


# ── ingestion (Rebuild / Resync buttons) ────────────────────────────────────

@router.get("/ingest/preview")
def ingest_preview(book: int | None = None):
    """Dry-run diff + cost estimate. May take ~30s if a manuscript needs a
    fresh Pages export."""
    from src.discovery import discover_books
    from src.extractor import estimate_extraction_cost
    from src.ingestion import diff_chunks, load_and_chunk_book, load_hash_index

    s = get_state()
    books = discover_books(s.cfg)
    if book is not None:
        books = [b for b in books if b.number == book]
    index = load_hash_index(s.cfg)
    plan, changed, changed_chunks = [], 0, []
    for b in books:
        chunks = load_and_chunk_book(s.cfg, b)
        if chunks is None:
            plan.append({"book": b.number, "title": b.title, "error": "extraction failed"})
            continue
        d = diff_chunks(chunks, index, b.number)
        changed_chunks.extend(d.changed)
        changed += len(d.changed)
        plan.append({"book": b.number, "title": b.title, "new": len(d.new),
                     "updated": len(d.updated), "unchanged": len(d.unchanged),
                     "deleted": len(d.deleted_ids)})
    est = estimate_extraction_cost(changed_chunks, s.cfg.extraction_model)
    return {"plan": plan, "changed_chunks": changed,
            "estimated_cost_usd": est["estimated_cost_usd"],
            "model": s.cfg.extraction_model}


@router.post("/ingest/run")
def ingest_run(book: int | None = None, full: bool = False):
    with _ingest_lock:
        running = _ingest["proc"] is not None and _ingest["proc"].poll() is None
        # Also refuse while the previous run's post-ingest writes (orphan GC +
        # index reload) are still in flight: those run in _watch after the
        # subprocess exits and write to the same SQLite DB, so starting a new
        # ingest subprocess now would put two writers in contention.
        if running or _ingest["post_processing"]:
            audit.log_event("ingest_refused", "an ingestion run is already in progress",
                            book=book, started_at=_ingest["started_at"])
            raise HTTPException(409, "an ingestion run is already in progress")
        log_path = REPO_ROOT / "logs" / "ingest_ui.log"
        log_path.parent.mkdir(exist_ok=True)
        cmd = [sys.executable, str(REPO_ROOT / "ingest.py"), "--yes"]
        if book is not None:
            cmd += ["--book", str(book)]
        # --full ignores the stored chunk hashes so every chapter is re-embedded
        # and re-extracted, not just what changed. Composes with --book (full
        # re-ingest of a single book); ingest.py only forbids --full + --re-extract.
        if full:
            cmd.append("--full")
        with open(log_path, "w") as out:
            _ingest["proc"] = subprocess.Popen(
                cmd, cwd=REPO_ROOT, stdout=out, stderr=subprocess.STDOUT)
        _ingest["log_path"] = log_path
        _ingest["started_at"] = datetime.now().isoformat()

        # notify the bell when the background sync exits
        proc = _ingest["proc"]
        s = get_state()
        title = (dict(s.db.execute(
            "SELECT DISTINCT book_number, book_title FROM chunks")).get(book)
            if book is not None else None)
        scope = title or "all books"

        audit.log_event("ingest_started",
                        f"{'full re-ingest' if full else 're-ingest'} of {scope} started",
                        book=book, full=full, log=str(log_path))

        def _watch(proc=proc, scope=scope, title=title, log_path=log_path):
            # success and no-op runs self-report from ingest.py with a full
            # summary; the watcher only covers crashes that never got there
            code = proc.wait()
            audit.log_event("ingest_exited", f"re-ingest of {scope} exited",
                            exit_code=code)
            if code == 0:
                # Mark post-processing so a concurrently-due ingest waits: the
                # GC + index reload below write to the same SQLite DB, and a
                # second ingest subprocess starting now would contend for the
                # write lock. Cleared in finally so a failure can't wedge it on.
                with _ingest_lock:
                    _ingest["post_processing"] = True
                try:
                    # chapters may have been renumbered or removed by this sync:
                    # purge enrichment rows (events/summaries) stranded at chapter
                    # numbers that no longer exist, or reviews serve the old
                    # numbering back as duplicate "earlier" story material.
                    # get_state().db is thread-local — safe from this thread.
                    try:
                        from ..enrich import gc_orphans
                        removed = gc_orphans(get_state().db)
                        if removed:
                            audit.log_event(
                                "enrich_gc",
                                "purged stale enrichment rows after re-ingest",
                                rows=removed)
                    except Exception:
                        log.exception("post-ingest enrichment GC failed")
                    # The subprocess rewrote the Chroma segments under this
                    # process; our cached client/collection is now stale and would
                    # serve broken semantic search (blank review bubbles) until a
                    # restart. Rebuild the search stack against the new segments.
                    try:
                        get_state().reload_index()
                        audit.log_event("index_reloaded",
                                        "rebuilt search stack after re-ingest")
                    except Exception:
                        log.exception("post-ingest index reload failed")
                finally:
                    with _ingest_lock:
                        _ingest["post_processing"] = False
            if code != 0:
                from .. import notify
                # ingest_ui.log is truncated ('w') at the start of the next
                # run, which clobbers this run's traceback before anyone reads
                # it. Preserve failed runs under a timestamped name (keeping the
                # last 5) and point the notification at the saved copy.
                ref = "logs/ingest_ui.log"
                try:
                    import shutil
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    saved = log_path.with_name(f"ingest_fail_{stamp}.log")
                    shutil.copyfile(log_path, saved)
                    ref = f"logs/{saved.name}"
                    for old in sorted(log_path.parent.glob("ingest_fail_*.log"))[:-5]:
                        old.unlink()
                except Exception:
                    log.exception("failed to preserve failed ingest log")
                notify.add("error", "Sync failed",
                           f"Re-ingest of {scope} exited with code {code}. "
                           f"See {ref}.",
                           book=title, action_url="/?pane=status")

        threading.Thread(target=_watch, daemon=True).start()
    return {"started": True}


@router.get("/ingest/status")
def ingest_status():
    proc = _ingest["proc"]
    tail = ""
    if _ingest["log_path"] and Path(_ingest["log_path"]).exists():
        tail = Path(_ingest["log_path"]).read_text(errors="replace")[-4000:]
    running = proc is not None and proc.poll() is None
    done = proc is not None and proc.poll() is not None
    if done:
        # data changed under us — force rebuild of derived views
        get_state().canon._map_state = ""
    return {"running": running, "finished": done,
            "exit_code": proc.poll() if proc else None,
            "started_at": _ingest["started_at"], "log_tail": tail}

"""Books pane + chapter text + ingestion control (cost-gated)."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config import REPO_ROOT

from ..deps import get_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_ingest = {"proc": None, "log_path": None, "started_at": None}
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
    """Reconstruct a full chapter from its ordered chunks."""
    s = get_state()
    rows = s.db.execute(
        """SELECT text, pov_character, date_line FROM chunks
           WHERE book_number = ? AND chapter_number = ?
           ORDER BY chunk_index""", (book, chapter)).fetchall()
    if not rows:
        raise HTTPException(404, "chapter not found")
    return {"book": book, "chapter": chapter,
            "pov": rows[0][1], "date": rows[0][2],
            "text": "\n\n".join(r[0] for r in rows)}


@router.get("/books/{book}/cover")
def book_cover(book: int):
    """Serve the dust-jacket front cover (read-only) if the book has one."""
    from fastapi.responses import FileResponse

    from src.discovery import discover_books
    s = get_state()
    match = next((b for b in discover_books(s.cfg) if b.number == book), None)
    if match is None:
        raise HTTPException(404, "unknown book")
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
def ingest_run(book: int | None = None):
    with _ingest_lock:
        if _ingest["proc"] is not None and _ingest["proc"].poll() is None:
            raise HTTPException(409, "an ingestion run is already in progress")
        log_path = REPO_ROOT / "logs" / "ingest_ui.log"
        log_path.parent.mkdir(exist_ok=True)
        cmd = [sys.executable, str(REPO_ROOT / "ingest.py"), "--yes"]
        if book is not None:
            cmd += ["--book", str(book)]
        with open(log_path, "w") as out:
            _ingest["proc"] = subprocess.Popen(
                cmd, cwd=REPO_ROOT, stdout=out, stderr=subprocess.STDOUT)
        _ingest["log_path"] = log_path
        _ingest["started_at"] = datetime.now().isoformat()
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

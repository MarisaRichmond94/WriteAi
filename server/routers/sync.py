"""Loom -> WriteAI drift detection.

Loom's canon export writes a "<Title>.manifest.json" sidecar next to each
manuscript describing what canon looks like right now (per-chapter numbers,
hashes, word counts, export timestamp). Comparing that against the chunks
table answers "is the index behind the books?" without parsing a manuscript
or running an ingest.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter

from src.discovery import discover_books

from ..deps import get_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _indexed_chapters(s, book) -> set[int]:
    """Chapter numbers the index holds for a book, keyed by stable ID (KAN-12).

    Prefers loom_book_id: book_number is positional, so inserting or reordering
    a book silently repoints this lookup at another book's rows — drift
    detection would then compare the wrong manifest against the wrong index and
    report confidently wrong answers.

    Falls back to book_number when the book has no Loom identity (never
    canon-exported) or when nothing in the index carries the ID yet (chunks
    ingested before this change). The fallback is what the code always did, so
    the worst case is unchanged behaviour rather than a regression.
    """
    if book.loom_book_id:
        rows = {r[0] for r in s.db.execute(
            "SELECT DISTINCT chapter_number FROM chunks WHERE loom_book_id = ?",
            (book.loom_book_id,))}
        if rows:
            return rows
        log.debug("book %d (%s) has a Loom id but no chunks carry it yet — "
                  "falling back to book_number", book.number, book.title)
    return {r[0] for r in s.db.execute(
        "SELECT DISTINCT chapter_number FROM chunks WHERE book_number = ?",
        (book.number,))}


def book_sync_state(s, book_number: int) -> tuple[bool, dict[int, str]]:
    """(index matches the manifest?, manifest chapter number -> Loom chapter
    id) for one book. (False, {}) when no manifest is readable — callers must
    treat that as "unknown", not as drift."""
    for b in discover_books(s.cfg):
        if b.number != book_number:
            continue
        manifest_path = b.folder / f"{b.title}.manifest.json"
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return (False, {})
        chapters = [c for c in m.get("chapters", [])
                    if c.get("number") is not None and c.get("id")]
        num_to_id = {c["number"]: c["id"] for c in chapters}
        # Compare the index against canon chapters that HAVE PROSE. A stubbed
        # chapter -- created to write later, wordCount 0 -- produces no chunks,
        # so it can never appear in the index. Requiring equality against all
        # of canon meant one stub marked its book permanently out of sync,
        # which in turn blocked _auto_reconcile for that book forever: its
        # outline could not self-heal, and renumbering went unnoticed.
        # Observed on The Secrets We Keep, stubs at chapters 32 and 43.
        #
        # num_to_id still carries EVERY canon chapter, stubs included, because
        # it is also the canon identity set used to decide which outline cards
        # have left canon. Dropping stubs from it would delete their cards.
        written = {c["number"] for c in chapters if c.get("wordCount")}
        index_ch = _indexed_chapters(s, b)
        return (written == index_ch, num_to_id)
    return (False, {})


@router.get("/sync/status")
def sync_status():
    """Per-book freshness of the index vs Loom's canon-export manifests.

    A book is 'behind' when the manifest lists chapter numbers the index
    doesn't have, or the index has numbers the manifest doesn't (a mid-book
    insertion shows up as both). Books without a readable manifest report
    manifest_found=False — callers should treat that as "unknown", not as
    drift; unnumbered chapters (part dividers) are outside the comparison.
    """
    s = get_state()
    books = []
    stale = 0
    for book in discover_books(s.cfg):
        manifest_path = book.folder / f"{book.title}.manifest.json"
        entry: dict = {"book": book.number, "title": book.title,
                       "manifest_found": manifest_path.exists()}
        if entry["manifest_found"]:
            try:
                m = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log.warning("unreadable manifest for book %d: %s",
                            book.number, manifest_path, exc_info=True)
                entry["manifest_found"] = False
                books.append(entry)
                continue
            manifest_ch = {c["number"] for c in m.get("chapters", [])
                           if c.get("number") is not None}
            # Per-book rather than one bulk scan: the lookup now keys on
            # loom_book_id where available (KAN-12), which a single
            # GROUP BY book_number can't express. Five books, five cheap
            # indexed queries.
            index_ch = _indexed_chapters(s, book)
            missing = sorted(manifest_ch - index_ch)
            extra = sorted(index_ch - manifest_ch)
            entry.update({
                "exported_at": m.get("exportedAt"),
                "manifest_chapters": len(manifest_ch),
                "indexed_chapters": len(index_ch),
                "missing_chapters": missing,
                "extra_chapters": extra,
                "behind": bool(missing or extra),
            })
            stale += 1 if entry["behind"] else 0
        books.append(entry)

    hashes = s.cfg.chunk_hashes_path
    last_synced = (datetime.fromtimestamp(hashes.stat().st_mtime).isoformat()
                   if hashes.exists() else None)
    return {"books": books, "stale_count": stale, "last_synced": last_synced}

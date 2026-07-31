"""Book and chapter discovery.

Books are folders directly under BOOKS_DIR whose names match
BOOK_PREFIX_PATTERN (default: starts with digits + period, e.g.
"1. Nobody's Hero"). Everything else is ignored. Books are ordered by their
numeric prefix, never alphabetically.

The canonical manuscript inside a book folder is the file at the folder ROOT
whose stem exactly matches the book title (e.g. "2. Faded/Faded.pages") —
this deliberately skips alternates ("Split - Alt.pages"), old drafts under
Versions/, PDFs of the same book, and design files.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .parser import SUPPORTED_SUFFIXES

log = logging.getLogger(__name__)

# Preference order when a book has the same title in multiple formats.
# .txt first: Loom's canon export writes a deterministic "<Title>.txt"
# sidecar (one line per paragraph, footnotes excluded) precisely so
# ingestion can read it headlessly — no Pages.app, no conversion cache.
# .pages remains the author's format; it is only parsed when no sidecar
# exists.
_FORMAT_PREFERENCE = [".txt", ".docx", ".pages", ".md", ".pdf"]


@dataclass
class Book:
    number: int
    title: str
    folder: Path
    manuscript: Path
    # Stable Loom identity, read from the manifest sidecar (KAN-12).
    #
    # `number` and `title` are both derived from the folder name, which makes
    # them presentational, not identifying: `number` survives a rename but
    # breaks on insertion or reordering, `title` does the reverse. Loom's cuids
    # survive both. The manifest has carried them since manifestVersion 1 —
    # nothing here consumed them until now.
    #
    # None when no manifest is readable (a book Loom has never canon-exported).
    # Callers must treat None as "unknown identity" and fall back to number or
    # title rather than assuming a match.
    loom_book_id: str | None = None
    loom_series_id: str | None = None


def _find_manuscript(folder: Path, title: str) -> Path | None:
    for suffix in _FORMAT_PREFERENCE:
        candidate = folder / f"{title}{suffix}"
        if candidate.exists():
            return candidate
    # Fallback: a single supported file at the root (excluding obvious alternates)
    candidates = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
        and "alt" not in p.stem.lower()
    ]
    if len(candidates) == 1:
        log.info("using %s as manuscript for '%s' (no exact title match)",
                 candidates[0].name, title)
        return candidates[0]
    return None


def _read_loom_identity(folder: Path, title: str) -> tuple[str | None, str | None]:
    """Pull (loom_book_id, loom_series_id) out of the manifest sidecar.

    Deliberately forgiving: a missing, unreadable, or malformed manifest yields
    (None, None) rather than raising. Discovery runs on every sync and must not
    be brought down by one bad sidecar — the caller degrades to number/title
    matching, which is what it did before KAN-12 anyway.

    The manifest is still LOCATED by folder and title. Locating it is the last
    title-dependent step; once it is open, identity is stable.
    """
    path = folder / f"{title}.manifest.json"
    if not path.exists():
        return (None, None)
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("unreadable manifest for '%s' (%s) — falling back to "
                    "number/title identity", title, exc)
        return (None, None)
    book_id = m.get("bookId")
    series_id = m.get("seriesId")
    if not book_id:
        log.warning("manifest for '%s' has no bookId (manifestVersion=%s) — "
                    "falling back to number/title identity",
                    title, m.get("manifestVersion"))
    return (book_id or None, series_id or None)


def loom_book_id_for(cfg, number: int) -> str | None:
    """Stable Loom id for a book number, or None when it can't be resolved.

    The bridge for callers that only have a positional number (existing route
    params, stored outline keys) but want to query by stable identity. Returning
    None is normal — the caller falls back to number matching.
    """
    for b in discover_books(cfg):
        if b.number == number:
            return b.loom_book_id
    return None


def discover_books(cfg) -> list[Book]:
    """Scan BOOKS_DIR for book folders; return them in series order."""
    books: list[Book] = []
    for entry in sorted(cfg.books_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not cfg.book_prefix_pattern.search(entry.name):
            continue
        digits = re.search(r"\d+", entry.name)
        if digits is None:
            log.warning("folder matches BOOK_PREFIX_PATTERN but has no number: %s",
                        entry.name)
            continue
        number = int(digits.group())
        # Title = folder name with the matched prefix stripped
        title = cfg.book_prefix_pattern.sub("", entry.name).strip()
        manuscript = _find_manuscript(entry, title)
        if manuscript is None:
            log.warning("no manuscript found for book %d (%s) — skipping", number, title)
            continue
        loom_book_id, loom_series_id = _read_loom_identity(entry, title)
        books.append(Book(number=number, title=title, folder=entry,
                          manuscript=manuscript,
                          loom_book_id=loom_book_id,
                          loom_series_id=loom_series_id))

    books.sort(key=lambda b: b.number)
    return books

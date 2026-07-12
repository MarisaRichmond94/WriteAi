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
        books.append(Book(number=number, title=title, folder=entry, manuscript=manuscript))

    books.sort(key=lambda b: b.number)
    return books

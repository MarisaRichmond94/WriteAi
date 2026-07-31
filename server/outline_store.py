"""Keying and migration for the plan outline store (KAN-24).

`writer_data/plan_outline.json` used to be keyed by BOOK NUMBER:

    {"1": [...cards], "2": [...cards]}

Book number is positional. Insert or reorder a book in Loom and every outline
shifts — 300+ cards silently attach to the wrong books, with nothing to detect
it. KAN-12 made Loom's cuids available; this module keys the store on them:

    {"cmp8wtcs3000tzufxcrda4qg2": [...cards], ...}

Everything that touches the store goes through here so the key discipline lives
in ONE place. Nine call sites across plan.py and review.py previously each did
`str(book)` by hand, which is exactly how one gets missed.

Migration is lazy and idempotent: numeric keys are re-keyed on load whenever
their book resolves to a cuid, and persisted. A book that cannot be resolved
(never canon-exported, or the manifest is mid-write) keeps its numeric key and
is retried on the next load — never dropped, never merged blindly.
"""

from __future__ import annotations

import logging

from src.discovery import loom_book_id_for

from . import writer_store
from .deps import get_state

log = logging.getLogger(__name__)


def outline_key(book: int) -> str:
    """Store key for a book: its Loom cuid, or the legacy number as fallback.

    The fallback matters. A book with no readable manifest still needs its
    outline to load and save; falling back to the number keeps it working
    exactly as it did before, and the next load migrates it once the manifest
    is readable again.
    """
    try:
        loom_id = loom_book_id_for(get_state().cfg, book)
    except Exception:
        log.warning("could not resolve a stable outline key for book %s — "
                    "falling back to its number", book, exc_info=True)
        loom_id = None
    return loom_id or str(book)


def load_outlines() -> dict:
    """The outline store, with any legacy numeric keys migrated to cuids.

    Persists only when something actually moved, so an already-migrated store
    is a pure read.
    """
    outlines = writer_store.plan_outline()
    changed = False

    for legacy in [k for k in outlines if k.isdigit()]:
        key = outline_key(int(legacy))
        if key == legacy:
            continue                      # unresolvable; leave it, retry later
        if key in outlines:
            # Both shapes present for one book. Do NOT merge or overwrite —
            # one of them holds cards the writer can see, and guessing which
            # risks discarding them. Leave both and say so.
            log.error("outline store has BOTH %r and %r for the same book; "
                      "leaving them untouched — resolve by hand", legacy, key)
            continue
        outlines[key] = outlines.pop(legacy)
        changed = True
        log.info("migrated outline key %r -> %r (%d cards)",
                 legacy, key, len(outlines[key]))

    if changed:
        writer_store.save_plan_outline(outlines)
    return outlines


def save_outlines(outlines: dict) -> None:
    writer_store.save_plan_outline(outlines)


def chapters_for(book: int) -> list:
    """Read-only convenience for callers that only want a book's cards.

    Falls back to the legacy numeric key so a not-yet-migrated store still
    reads correctly.
    """
    outlines = writer_store.plan_outline()
    key = outline_key(book)
    return outlines.get(key) or outlines.get(str(book), [])

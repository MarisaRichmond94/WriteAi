"""Condensed per-book story digests: build, freshness, and lookup.

Review and chat inject a chapter-by-chapter bible for every earlier/selected
book into the CACHED system block — ~46K tokens on a book-5 review, almost
all of it per-chapter prose summaries. A digest holds the continuity a later
book actually leans on (arc, reveals, character outcomes, open threads) in
~1.5K tokens, condensed once by the cheap extraction model and stored in
sqlite (book_digests).

Staleness is self-healing, not monitored: each digest stores a hash of the
exact text it was condensed from, and the enrichment run — the only pipeline
that rewrites chapter summaries — ends by refreshing whichever books' hashes
no longer match (fresh books skip at zero API cost). If a refresh fails, the
read path serves the full bible instead (a bigger prompt, never a thinner
one). scripts/build_book_digests.py is the manual fallback, mirroring
scripts/resolve_chronology.py — recovery, not routine.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from datetime import datetime, timezone

from src.costlog import log_cost
from src.extractor import _pricing_for

log = logging.getLogger(__name__)

DIGESTS_DDL = """CREATE TABLE IF NOT EXISTS book_digests (
    book_number INTEGER PRIMARY KEY,
    input_hash  TEXT NOT NULL,
    digest_md   TEXT NOT NULL,
    model       TEXT,
    created_at  TEXT
)"""

DIGEST_SYSTEM = """You condense the chapter-by-chapter summary of one book of a fiction series into a compact continuity digest for the series' author. The digest replaces the full summary as background context when the author works on LATER books, so keep exactly what later books lean on and drop scene-level detail.

Structure the digest as:
## Synopsis
One tight paragraph: premise, central conflict, how it resolves.
## Arc
The book's movement in 3-6 phases, each with its chapter range, e.g. "(Ch 1-9)".
## Major reveals & turning points
Bulleted, each with its chapter cite "(Ch N)". Include only reveals that change what characters or readers know going forward.
## Character outcomes
Bulleted: deaths, births, relationship changes, secrets learned or exposed, and where each major character stands at the book's end.
## Open threads
Bulleted: questions, promises, and foreshadowing left unresolved at the end of this book.

Rules: derive everything from the provided summaries — never invent or embellish. Preserve exact character and place names. Keep the whole digest under 1,000 words."""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_source(s, book: int) -> str:
    """The exact text a stored digest is condensed from — the chapters-only
    compact bible. Its hash is the freshness check: re-enrichment or a re-sync
    changes the summaries (or their POV/date headers), which changes the hash,
    which retires the digest until the next refresh rebuilds it.

    `s` needs only .db and .canon — the enrichment runner passes a shim, the
    routers pass the real AppState. Imported lazily: routers import this
    module, and books.py imports enrich, so a module-level import here would
    close an import cycle."""
    from .routers.books import _build_bible
    _, md = _build_bible(s, book, compact=True, characters=False)
    return md


def lookup_digest(db, book: int, source_md: str) -> str | None:
    """The stored digest for `book`, or None when absent, stale (hash of
    `source_md` no longer matches), or the table hasn't been built yet."""
    try:
        row = db.execute(
            "SELECT digest_md FROM book_digests "
            "WHERE book_number = ? AND input_hash = ?",
            (book, _hash(source_md))).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def book_digest(s, book: int) -> str | None:
    """Fresh condensed digest for `book`, or None. Callers fall back to the
    full bible, so a missing digest degrades to the legacy (bigger, costlier)
    prompt — never to a thinner one."""
    try:
        source = digest_source(s, book)
    except Exception:
        return None
    digest = lookup_digest(s.db, book, source)
    if digest is None:
        log.info("book %s digest missing or stale — sending the full bible; "
                 "the next enrichment run refreshes it (or run "
                 "scripts/build_book_digests.py)", book)
    return digest


def refresh_digests(db, cfg, client, books, source_for, *,
                    force: bool = False, on_book=None) -> dict:
    """Build or refresh the digests for `books`, skipping fresh ones — a book
    whose source hash still matches costs one sqlite lookup and no API call,
    so this is safe to run over every book at the end of every enrichment run.

    `source_for(book)` returns the digest source text (see digest_source);
    it is injected so the enrichment runner's thread-local db/canon and the
    server's AppState can both drive the same loop. Per-book failures are
    contained: the stale digest stays retired and the read path falls back
    to the full bible. Spend is ledgered per book under surface="digest".
    Returns {"built", "skipped", "failed", "cost_usd"}."""
    db.execute(DIGESTS_DDL)
    db.commit()
    model = cfg.extraction_model
    in_p, out_p = _pricing_for(model)
    stats = {"built": 0, "skipped": 0, "failed": 0, "cost_usd": 0.0}
    for book in books:
        try:
            source = source_for(book)
            h = _hash(source)
            if not force:
                row = db.execute("SELECT input_hash FROM book_digests "
                                 "WHERE book_number = ?", (book,)).fetchone()
                if row and row[0] == h:
                    stats["skipped"] += 1
                    continue
            row = db.execute("SELECT DISTINCT book_title FROM chunks "
                             "WHERE book_number = ?", (book,)).fetchone()
            if row is None:
                stats["failed"] += 1
                continue
            title = row[0]
            t0 = time.monotonic()
            resp = client.messages.create(
                model=model, max_tokens=4000, system=DIGEST_SYSTEM,
                messages=[{"role": "user", "content":
                           f"Book {book} of the series: {title}\n\n{source}"}])
            body = next((b.text for b in resp.content if b.type == "text"), "")
            if not body.strip():
                log.warning("digest build for book %s returned no text", book)
                stats["failed"] += 1
                continue
            digest = (f"# Story Bible (condensed) — Book {book}: {title}\n\n"
                      f"_Condensed from the chapter-by-chapter bible; chapter "
                      f"cites refer to Book {book}._\n\n{body.strip()}")

            u = resp.usage
            cost = (u.input_tokens * in_p + u.output_tokens * out_p) / 1_000_000
            log_cost(cfg, surface="digest", model=model,
                     usage={"input_tokens": u.input_tokens,
                            "output_tokens": u.output_tokens,
                            "cache_write_tokens": 0, "cache_read_tokens": 0},
                     cost_usd=round(cost, 4),
                     latency_ms=int((time.monotonic() - t0) * 1000),
                     extra={"book": book})

            db.execute("INSERT OR REPLACE INTO book_digests "
                       "(book_number, input_hash, digest_md, model, created_at) "
                       "VALUES (?, ?, ?, ?, ?)",
                       (book, h, digest, model,
                        datetime.now(timezone.utc).isoformat()))
            db.commit()
            stats["built"] += 1
            stats["cost_usd"] = round(stats["cost_usd"] + cost, 4)
            log.info("book %s digest rebuilt ($%.4f)", book, cost)
        except Exception as e:
            stats["failed"] += 1
            log.warning("digest build failed for book %s (review/chat fall "
                        "back to the full bible): %s", book, e)
        finally:
            if on_book:
                on_book(book)
    return stats

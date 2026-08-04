"""Regression tests for enrichment re-running the whole tail of a book after
a chapter is inserted.

`enrich_state` scoped its per-chapter cache as `events:{book}.{chapter}`. That
is the positional keying LOOM-65 removed from `chapter_summaries`, and it
failed identically: insert a chapter at 40 and chapter 41 now holds what 40
used to, so its stored content hash no longer matches and it re-enriches — as
does every chapter below it, one model call each, for prose nobody edited.

Keyed by Loom's chapter cuid the cache follows the chapter through a
renumbering. The second half of that bargain is `gc_orphans`, whose numeric
sweep must not mistake a cuid-keyed row for an orphan and delete it.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_enrich_scope_identity -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import enrich  # noqa: E402
from server.enrich import events_scope, gc_orphans  # noqa: E402


class EventsScope(unittest.TestCase):

    def setUp(self):
        self._real = enrich._loom_ids
        # book 2: chapter 40 is cuid A, chapter 41 is cuid B.
        ids = {(2, 40): "cmch40aaaa", (2, 41): "cmch41bbbb"}
        enrich._loom_ids = lambda cfg, b, c: ("bk", "sr", ids.get((b, c)))
        self.addCleanup(setattr, enrich, "_loom_ids", self._real)

    def test_scope_follows_the_chapter_not_the_number(self):
        """The whole point: the same chapter keeps its cache key after an
        insert renumbers it from 40 to 41."""
        before = events_scope(None, 2, 40)
        # a chapter is inserted above it; the same prose is now chapter 41
        enrich._loom_ids = lambda cfg, b, c: (
            "bk", "sr", {(2, 41): "cmch40aaaa"}.get((b, c)))
        after = events_scope(None, 2, 41)
        self.assertEqual(before, after)
        self.assertEqual(before, "events:cmch40aaaa")

    def test_two_chapters_never_share_a_scope(self):
        self.assertNotEqual(events_scope(None, 2, 40), events_scope(None, 2, 41))

    def test_falls_back_to_the_number_without_a_manifest(self):
        """A book never canon-exported has no cuids. That is the pre-LOOM-65
        behaviour — the floor, not a regression."""
        enrich._loom_ids = lambda cfg, b, c: (None, None, None)
        self.assertEqual(events_scope(None, 7, 3), "events:7.3")


class GcOrphansKeepsIdentityRows(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        gc_orphans(self.db)  # creates the enrichment tables
        self.db.execute(
            """CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY,
                   book_number INTEGER, chapter_number INTEGER)""")
        self.db.execute(
            "INSERT INTO chunks VALUES ('b02.c040.s01.k00', 2, 40)")
        self.db.commit()

    def _scopes(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT scope FROM enrich_state")}

    def test_a_cuid_row_survives_the_numeric_sweep(self):
        """Without the GLOB guard this row matched 'not a live book.chapter'
        and was deleted on every single run, undoing the whole change."""
        self.db.execute(
            "INSERT INTO enrich_state (scope, content_hash) "
            "VALUES ('events:cmch40aaaa', 'h')")
        self.db.commit()
        gc_orphans(self.db)
        self.assertIn("events:cmch40aaaa", self._scopes())

    def test_a_stale_numeric_row_is_still_collected(self):
        """The original behaviour must be intact for rows that predate this."""
        self.db.execute(
            "INSERT INTO enrich_state (scope, content_hash) "
            "VALUES ('events:2.99', 'h')")
        self.db.commit()
        self.assertEqual(gc_orphans(self.db), 1)
        self.assertNotIn("events:2.99", self._scopes())

    def test_a_live_numeric_row_is_kept(self):
        self.db.execute(
            "INSERT INTO enrich_state (scope, content_hash) "
            "VALUES ('events:2.40', 'h')")
        self.db.commit()
        gc_orphans(self.db)
        self.assertIn("events:2.40", self._scopes())

    def test_cuid_rows_are_collected_only_against_a_known_live_set(self):
        for scope in ("events:cmlive0000", "events:cmgone0000"):
            self.db.execute(
                "INSERT INTO enrich_state (scope, content_hash) VALUES (?, 'h')",
                (scope,))
        self.db.commit()

        # No live set: leave every cuid row alone rather than guess.
        gc_orphans(self.db, None)
        self.assertEqual(len(self._scopes()), 2)

        gc_orphans(self.db, {"cmlive0000"})
        self.assertEqual(self._scopes(), {"events:cmlive0000"})


if __name__ == "__main__":
    unittest.main()

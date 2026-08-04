"""Regression tests for chronology rows silently describing the wrong chapter.

`chapter_timeline` is keyed (book_number, chapter_number). Insert a chapter in
Loom and every chapter below it renumbers, so row (2, 41) now describes what
is chapter 42 today — every date in the tail of the book attributed one
chapter off. The failure is invisible: `_stored_assignments` sees complete
coverage, reports the book as already resolved, and the wrong answer survives
every subsequent run.

Comparing the stored Loom chapter cuid against the cuid of the chapter
currently at that number is what makes it visible.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_chronology_identity -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.chronology import _stored_assignments, _upsert_book, ensure_table  # noqa: E402

CHAPTERS = [{"chapter_number": n, "month": 5, "day": n} for n in (40, 41)]
ASSIGNED = {n: {"chapter_number": n, "story_year": 1, "temporal_mode": "primary",
                "confidence": 0.9, "rationale": "r"} for n in (40, 41)}


class StoredAssignmentsIdentity(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        ensure_table(self.db)

    def _seed(self, ids):
        _upsert_book(self.db, 2, CHAPTERS, ASSIGNED, set(), ids)
        self.db.commit()

    def test_a_renumbered_book_is_re_resolved_not_trusted(self):
        """The bug: chapter 41 is now a different chapter than the row
        describes, and the book must not be reported as already resolved."""
        self._seed({40: "cmch_a", 41: "cmch_b"})
        # a chapter was inserted above 41: what was 40 is now 41
        current = {40: "cmch_new", 41: "cmch_a"}
        self.assertIsNone(_stored_assignments(self.db, 2, CHAPTERS, current))

    def test_an_untouched_book_still_costs_nothing(self):
        """The other half: identity matching must not force a re-resolve of
        every book on every run. That would be a bill, not a fix."""
        ids = {40: "cmch_a", 41: "cmch_b"}
        self._seed(ids)
        assigned = _stored_assignments(self.db, 2, CHAPTERS, ids)
        self.assertIsNotNone(assigned)
        self.assertEqual(assigned[40]["story_year"], 1)

    def test_rows_predating_the_column_are_unknown_not_mismatched(self):
        """Degradation contract: a NULL id is unknown identity and falls back
        to the chapter number. Old rows keep working exactly as before."""
        self._seed({})  # nothing resolvable -> both ids NULL
        current = {40: "cmch_a", 41: "cmch_b"}
        self.assertIsNotNone(_stored_assignments(self.db, 2, CHAPTERS, current))

    def test_no_identity_available_behaves_exactly_as_before(self):
        self._seed({40: "cmch_a", 41: "cmch_b"})
        self.assertIsNotNone(_stored_assignments(self.db, 2, CHAPTERS, None))
        self.assertIsNotNone(_stored_assignments(self.db, 2, CHAPTERS, {}))

    def test_incomplete_coverage_still_returns_none(self):
        self._seed({40: "cmch_a", 41: "cmch_b"})
        extra = CHAPTERS + [{"chapter_number": 42, "month": 5, "day": 3}]
        self.assertIsNone(_stored_assignments(self.db, 2, extra, None))


class UpsertStampsIdentity(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        ensure_table(self.db)

    def _ids(self):
        return dict(self.db.execute(
            "SELECT chapter_number, loom_chapter_id FROM chapter_timeline"))

    def test_identity_is_written_with_the_row(self):
        _upsert_book(self.db, 2, CHAPTERS, ASSIGNED, set(), {40: "a", 41: "b"})
        self.assertEqual(self._ids(), {40: "a", 41: "b"})

    def test_a_rewrite_refreshes_a_stale_identity(self):
        """A renumbered chapter must take its CURRENT identity, not keep the
        one that was stamped before it moved."""
        _upsert_book(self.db, 2, CHAPTERS, ASSIGNED, set(), {40: "a", 41: "b"})
        _upsert_book(self.db, 2, CHAPTERS, ASSIGNED, set(), {40: "new", 41: "a"})
        self.assertEqual(self._ids(), {40: "new", 41: "a"})

    def test_manual_override_rows_are_still_never_rewritten(self):
        _upsert_book(self.db, 2, CHAPTERS, ASSIGNED, set(), {40: "a", 41: "b"})
        self.db.execute("UPDATE chapter_timeline SET manual_override = 1, "
                        "story_year = 99 WHERE chapter_number = 40")
        _upsert_book(self.db, 2, CHAPTERS, ASSIGNED, {(2, 40)}, {40: "z", 41: "z"})
        row = self.db.execute(
            "SELECT story_year, loom_chapter_id FROM chapter_timeline "
            "WHERE chapter_number = 40").fetchone()
        self.assertEqual(row, (99, "a"))

    def test_ensure_table_is_idempotent_on_a_pre_column_store(self):
        """The ALTER path: a store built before the column must gain it, and
        re-running must not fail."""
        db = sqlite3.connect(":memory:")
        db.execute("""CREATE TABLE chapter_timeline (
            book_number INTEGER NOT NULL, chapter_number INTEGER NOT NULL,
            story_year INTEGER NOT NULL, month INTEGER, day INTEGER,
            temporal_mode TEXT NOT NULL DEFAULT 'primary', confidence REAL,
            rationale TEXT, manual_override INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (book_number, chapter_number))""")
        ensure_table(db)
        ensure_table(db)
        cols = {r[1] for r in db.execute(
            "SELECT * FROM pragma_table_info('chapter_timeline')")}
        self.assertIn("loom_chapter_id", cols)


if __name__ == "__main__":
    unittest.main()

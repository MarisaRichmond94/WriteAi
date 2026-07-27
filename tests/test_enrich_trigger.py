"""Unit tests for the chapter-numbering enrichment trigger.

Enrichment normally waits for the writer's cadence (Settings -> Sync), but a
sync that adds or removes a chapter renumbers every downstream chapter and
strands its summary on the wrong number — visible on the plan page right
away. These tests cover the roster snapshot that detects that case, and the
rule that prose-only edits must NOT qualify (that is what keeps incremental
loom-event syncs from billing enrichment several times a day).

Run from the repo root:
    .venv/bin/python -m unittest tests.test_enrich_trigger -v
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.routers import books  # noqa: E402


class _FakeState:
    def __init__(self, db):
        self.db = db


def _seed(db, rows):
    db.execute("CREATE TABLE IF NOT EXISTS chunks ("
               "chunk_id TEXT PRIMARY KEY, book_number INT, "
               "chapter_number INT, text TEXT)")
    db.execute("DELETE FROM chunks")
    for book, ch, text in rows:
        db.execute("INSERT INTO chunks VALUES (?,?,?,?)",
                   (f"b{book:02d}.c{ch:03d}", book, ch, text))
    db.commit()


class ChapterRosterTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self._orig = books.get_state
        books.get_state = lambda: _FakeState(self.db)

    def tearDown(self):
        books.get_state = self._orig
        self.db.close()

    def test_roster_scoped_to_one_book(self):
        _seed(self.db, [(3, 1, "a"), (3, 2, "b"), (4, 1, "c")])
        self.assertEqual(books._chapter_roster(3), {(3, 1), (3, 2)})

    def test_roster_all_books_when_book_is_none(self):
        _seed(self.db, [(3, 1, "a"), (4, 1, "c")])
        self.assertEqual(books._chapter_roster(None), {(3, 1), (4, 1)})

    def test_roster_dedupes_multi_chunk_chapters(self):
        db = self.db
        db.execute("CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, "
                   "book_number INT, chapter_number INT, text TEXT)")
        for i in range(3):
            db.execute("INSERT INTO chunks VALUES (?,?,?,?)",
                       (f"k{i}", 3, 7, "x"))
        db.commit()
        self.assertEqual(books._chapter_roster(3), {(3, 7)})

    def test_roster_empty_on_read_failure(self):
        """A broken read must degrade to "no change detected", never to a
        spurious billed enrichment run."""
        books.get_state = lambda: _FakeState(sqlite3.connect(":memory:"))
        self.assertEqual(books._chapter_roster(3), set())


class NumberingChangeTest(unittest.TestCase):
    """The decision _watch makes from the two snapshots."""

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self._orig = books.get_state
        books.get_state = lambda: _FakeState(self.db)

    def tearDown(self):
        books.get_state = self._orig
        self.db.close()

    def _roster(self, rows):
        _seed(self.db, rows)
        return books._chapter_roster(3)

    def test_prose_edit_does_not_change_roster(self):
        before = self._roster([(3, 1, "old prose"), (3, 2, "b")])
        after = self._roster([(3, 1, "revised prose"), (3, 2, "b")])
        self.assertEqual(before, after)

    def test_inserted_chapter_changes_roster(self):
        """The real bug: a new chapter 20 pushes 20..67 down to 21..68."""
        before = self._roster([(3, c, "x") for c in range(19, 22)])
        after = self._roster([(3, c, "x") for c in range(19, 23)])
        self.assertNotEqual(before, after)
        self.assertEqual(sorted(c for _b, c in after - before), [22])

    def test_removed_chapter_changes_roster(self):
        before = self._roster([(3, c, "x") for c in range(1, 5)])
        after = self._roster([(3, c, "x") for c in range(1, 4)])
        self.assertNotEqual(before, after)
        self.assertEqual(sorted(c for _b, c in before - after), [4])

    def test_first_index_of_book_is_not_a_numbering_change(self):
        """An empty "before" is a cold start, not a renumbering — the guard in
        _watch requires a non-empty roster_before."""
        before = self._roster([])
        after = self._roster([(3, 1, "x")])
        self.assertFalse(bool(before))
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()

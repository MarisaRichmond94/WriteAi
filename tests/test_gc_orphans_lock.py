"""Regression tests for the write lock gc_orphans used to leak.

A DELETE opens a SQLite write transaction the moment it runs, whether or not
it matches any rows, and SQLite's single write lock is held until that
transaction ends. gc_orphans used to commit only when it had actually deleted
something, so the ordinary "nothing to clean up" path walked away holding the
lock. On the enrichment runner's long-lived connection that pinned the lock
for the length of the whole pass, and any ingest subprocess that started in
that window failed with "database is locked".

These tests use a real file-backed DB (not :memory:) because the bug is about
cross-connection locking, which a private in-memory DB cannot express.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_gc_orphans_lock -v
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.enrich import gc_orphans  # noqa: E402


class GcOrphansLockTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self._dir.name) / "series.sqlite")
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, "
                        "book_number INT, chapter_number INT)")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self._dir.cleanup()

    def _seed_chapters(self, pairs):
        for book, ch in pairs:
            self.db.execute("INSERT INTO chunks VALUES (?,?,?)",
                            (f"b{book}.c{ch}", book, ch))
        self.db.commit()

    def _other_writer_blocked(self) -> bool:
        """True if a second connection cannot take the write lock."""
        other = sqlite3.connect(self.path, timeout=0.5)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
            return False
        except sqlite3.OperationalError:
            return True
        finally:
            other.close()

    def test_releases_lock_when_nothing_to_collect(self):
        """The no-op path — the one that runs on almost every sync."""
        self._seed_chapters([(3, 1), (3, 2)])

        self.assertEqual(gc_orphans(self.db), 0)
        self.assertFalse(self.db.in_transaction,
                         "gc_orphans left a transaction open after deleting nothing")
        self.assertFalse(self._other_writer_blocked(),
                         "gc_orphans is still holding the write lock")

    def test_releases_lock_after_collecting(self):
        """The path that does delete rows must still commit its work."""
        self._seed_chapters([(3, 1)])
        gc_orphans(self.db)  # creates the enrichment tables
        self.db.execute("INSERT INTO chapter_summaries (book_number, "
                        "chapter_number, summary) VALUES (3, 1, 'kept')")
        self.db.execute("INSERT INTO chapter_summaries (book_number, "
                        "chapter_number, summary) VALUES (3, 99, 'orphan')")
        self.db.commit()

        self.assertEqual(gc_orphans(self.db), 1)
        self.assertFalse(self.db.in_transaction)
        self.assertFalse(self._other_writer_blocked())
        kept = [r[0] for r in self.db.execute(
            "SELECT summary FROM chapter_summaries ORDER BY chapter_number")]
        self.assertEqual(kept, ["kept"], "the deletion was not committed")

    def test_releases_lock_when_chunks_table_is_missing(self):
        """Cold start: ingest has never run, so the DELETEs raise."""
        self.db.execute("DROP TABLE chunks")
        self.db.commit()

        self.assertEqual(gc_orphans(self.db), 0)
        self.assertFalse(self.db.in_transaction)
        self.assertFalse(self._other_writer_blocked())


if __name__ == "__main__":
    unittest.main()

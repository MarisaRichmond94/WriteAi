"""Regression tests for enrichment rows served under the wrong chapter.

This is the other half of keying `enrich_state` by chapter cuid, and without
it that change is a correctness REGRESSION rather than a saving.

The cache is keyed by identity; both output tables are still keyed by NUMBER
(`chapter_summaries` by (book_number, chapter_number), `events` deleted and
reinserted by the same pair). So after an insert, every later chapter
correctly reports "my prose has not changed" and is skipped — and its summary
and events stay parked at a number that now belongs to a different chapter.
The plan page shows chapter 41's summary on chapter 42 and nothing will ever
ask to regenerate it.

The old positional key hid this by missing the cache on every renumbering and
paying to regenerate the tail. That was expensive, not correct.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_reposition_renumbered -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import enrich  # noqa: E402
from server.enrich import ensure_tables, reposition_renumbered_chapters  # noqa: E402


class Reposition(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        ensure_tables(self.db)
        self.db.execute("""CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY,
                           book_number INTEGER, chapter_number INTEGER)""")
        self.db.execute("INSERT INTO chunks VALUES ('c', 2, 40)")
        self.db.commit()
        self.addCleanup(enrich._LOOM_ID_CACHE.clear)

    def manifest(self, numbers_to_ids):
        """Pretend the book's manifest maps these chapter numbers to cuids."""
        enrich._LOOM_ID_CACHE.clear()
        enrich._LOOM_ID_CACHE[2] = ("bk", "sr", dict(numbers_to_ids))

    def summaries(self):
        return dict(self.db.execute(
            "SELECT chapter_number, summary FROM chapter_summaries "
            "WHERE book_number = 2"))

    def seed_summary(self, chapter, summary, cuid):
        self.db.execute(
            "INSERT INTO chapter_summaries (book_number, chapter_number, "
            "summary, loom_chapter_id) VALUES (2,?,?,?)", (chapter, summary, cuid))
        self.db.commit()

    def test_an_insert_moves_the_tail_down_by_one(self):
        """The bug, end to end: a chapter is inserted at 40, so what was 40/41
        is now 41/42 and their summaries must follow them."""
        self.seed_summary(40, "summary of A", "cu_a")
        self.seed_summary(41, "summary of B", "cu_b")
        self.manifest({40: "cu_new", 41: "cu_a", 42: "cu_b"})

        self.assertEqual(reposition_renumbered_chapters(self.db, None), 2)
        self.assertEqual(self.summaries(),
                         {41: "summary of A", 42: "summary of B"})

    def test_rows_moving_through_each_other_do_not_collide(self):
        """40->41 while 41->42 is a head-on collision against the (book,
        chapter) primary key if applied in place. This is the case that makes
        a naive UPDATE throw."""
        for n, (s, cid) in enumerate([("A", "cu_a"), ("B", "cu_b"),
                                      ("C", "cu_c")], start=40):
            self.seed_summary(n, s, cid)
        self.manifest({41: "cu_a", 42: "cu_b", 43: "cu_c"})

        reposition_renumbered_chapters(self.db, None)
        self.assertEqual(self.summaries(), {41: "A", 42: "B", 43: "C"})

    def test_a_deleted_chapter_shifts_the_tail_up(self):
        self.seed_summary(40, "A", "cu_a")
        self.seed_summary(41, "B", "cu_b")
        self.manifest({40: "cu_b"})   # cu_a's chapter was deleted
        reposition_renumbered_chapters(self.db, None)
        # cu_b took slot 40; cu_a is no longer in the manifest and is left for
        # gc_orphans rather than silently deleted here.
        self.assertEqual(self.summaries()[40], "B")

    def test_a_stale_occupant_is_displaced_not_duplicated(self):
        """The row that was already sitting in the target slot is exactly the
        one that would otherwise be served under the wrong chapter."""
        self.seed_summary(41, "stale, from a chapter that no longer exists", None)
        self.seed_summary(40, "A", "cu_a")
        self.manifest({41: "cu_a"})
        reposition_renumbered_chapters(self.db, None)
        self.assertEqual(self.summaries(), {41: "A"})

    def test_an_unmoved_book_is_left_completely_alone(self):
        self.seed_summary(40, "A", "cu_a")
        self.manifest({40: "cu_a"})
        self.assertEqual(reposition_renumbered_chapters(self.db, None), 0)
        self.assertEqual(self.summaries(), {40: "A"})

    def test_rows_without_identity_are_never_moved(self):
        """Degradation contract: no cuid means events_scope also falls back to
        the number, so the old regenerate-on-mismatch path still covers them.
        The two keying schemes must agree per row."""
        self.seed_summary(40, "A", None)
        self.manifest({41: "cu_a"})
        self.assertEqual(reposition_renumbered_chapters(self.db, None), 0)
        self.assertEqual(self.summaries(), {40: "A"})

    def test_a_book_with_no_manifest_is_left_alone(self):
        self.seed_summary(40, "A", "cu_a")
        enrich._LOOM_ID_CACHE.clear()
        enrich._LOOM_ID_CACHE[2] = (None, None, {})
        self.assertEqual(reposition_renumbered_chapters(self.db, None), 0)
        self.assertEqual(self.summaries(), {40: "A"})

    def test_events_move_too_and_keep_their_order(self):
        for pos, title in enumerate(["first", "second"]):
            self.db.execute(
                """INSERT INTO events (book_number, chapter_number, position,
                       title, type, granularity, loom_chapter_id)
                   VALUES (2, 40, ?, ?, 'other', 'scene', 'cu_a')""",
                (pos, title))
        self.db.execute(
            """INSERT INTO events (book_number, chapter_number, position,
                   title, type, granularity, loom_chapter_id)
               VALUES (2, 41, 0, 'stale', 'other', 'scene', NULL)""")
        self.db.commit()
        self.manifest({41: "cu_a"})

        reposition_renumbered_chapters(self.db, None)
        rows = self.db.execute(
            "SELECT chapter_number, position, title FROM events "
            "ORDER BY chapter_number, position").fetchall()
        self.assertEqual(rows, [(41, 0, "first"), (41, 1, "second")])

    def test_running_twice_is_a_no_op_the_second_time(self):
        self.seed_summary(40, "A", "cu_a")
        self.manifest({41: "cu_a"})
        self.assertEqual(reposition_renumbered_chapters(self.db, None), 1)
        self.assertEqual(reposition_renumbered_chapters(self.db, None), 0)
        self.assertEqual(self.summaries(), {41: "A"})

    def test_no_write_lock_is_left_open_on_the_no_op_path(self):
        """Same hazard gc_orphans documents: a DELETE/UPDATE opens a write
        transaction even when it matches nothing, and the enrichment runner
        holds this connection across every LLM call in the pass."""
        self.manifest({40: "cu_a"})
        reposition_renumbered_chapters(self.db, None)
        self.assertFalse(self.db.in_transaction)


if __name__ == "__main__":
    unittest.main()

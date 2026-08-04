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
        self.db.commit()
        self.addCleanup(enrich.forget_loom_ids)

    def manifest(self, numbers_to_ids, indexed=None):
        """Pretend the book's manifest maps these chapter numbers to cuids.

        Also stocks `chunks`, because reposition now refuses to move rows for a
        book whose manifest and indexed prose disagree (LOOM-100) — so a
        fixture that describes a manifest without the matching prose describes
        a book that could not exist. `indexed` overrides for the tests that are
        *about* that disagreement; by default the prose matches the manifest.
        """
        enrich.forget_loom_ids()
        enrich._LOOM_ID_CACHE[2] = ("bk", "sr", dict(numbers_to_ids))
        numbers = sorted(numbers_to_ids) if indexed is None else sorted(indexed)
        self.db.execute("DELETE FROM chunks")
        self.db.executemany("INSERT INTO chunks VALUES (?, 2, ?)",
                            [(f"c{n}", n) for n in numbers])
        self.db.commit()

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

    # ── LOOM-100: the sweep must not delete a live chapter's only row ────────
    #
    # Book 3's rows were stamped one chapter late, so every row wanted to move
    # up by one. This pass moved 56 of them and deleted two more on the way
    # out — including chapter 43's summary, whose cuid the manifest still
    # listed. That deletion is the part no later pass can undo, and the part
    # that is decidable from the rows alone.
    #
    # What is NOT decidable here: a uniform shift is structurally identical to
    # a mid-book insert. Both move a suffix by one with each row keeping its
    # own cuid. That distinction lives in LOOM-98 (were the stamps written
    # against a current manifest?), and the insert tests above must keep
    # passing untouched — they do.

    def test_a_swap_is_still_applied(self):
        """Two rows exchanging numbers both move; the parking phase is what
        makes that safe, and the collision guard must not veto it."""
        self.seed_summary(40, "A", "cu_a")
        self.seed_summary(41, "B", "cu_b")
        self.manifest({40: "cu_b", 41: "cu_a"})
        self.assertEqual(reposition_renumbered_chapters(self.db, None), 2)
        self.assertEqual(self.summaries(), {40: "B", 41: "A"})

    def test_an_orphaned_occupant_is_still_swept(self):
        """The behaviour the guard must not cost us: a row whose cuid the
        manifest no longer lists is genuinely stale and still gets displaced."""
        self.seed_summary(41, "from a chapter that no longer exists", "cu_gone")
        self.seed_summary(40, "A", "cu_a")
        self.manifest({41: "cu_a"})
        self.assertEqual(reposition_renumbered_chapters(self.db, None), 1)
        self.assertEqual(self.summaries(), {41: "A"})

    def test_a_twin_already_in_the_target_slot_does_not_raise(self):
        """Pre-existing crash, found while writing these guards. Two rows share
        cu_a; the one at 41 is already where cu_a belongs, so it is neither a
        mover nor stale and nothing displaces it — and the other then UPDATEs
        straight into its primary key.

        That raised IntegrityError out of the middle of the enrichment run,
        which aborts the pass with a write transaction open. Refusing the move
        leaves the duplicate visible and the run alive."""
        self.seed_summary(41, "duplicate of A", "cu_a")
        self.seed_summary(40, "A", "cu_a")
        self.manifest({41: "cu_a"})
        self.assertEqual(reposition_renumbered_chapters(self.db, None), 0)
        self.assertEqual(self.summaries(), {40: "A", 41: "duplicate of A"})
        self.assertFalse(self.db.in_transaction)

    def test_a_manifest_behind_the_prose_blocks_the_whole_book(self):
        """LOOM-98's incident, contained. The index holds chapter 44; the
        manifest still describes a 43-chapter book, so every stamp in it was
        written against different numbering and none of it can be moved by."""
        self.seed_summary(42, "chapter 42's summary", "cu_43")   # mis-stamped
        self.seed_summary(43, "chapter 43's summary", "cu_44")   # mis-stamped
        self.manifest({42: "cu_42", 43: "cu_43", 44: "cu_44"},
                      indexed=[42, 43, 44, 45])

        self.assertEqual(reposition_renumbered_chapters(self.db, None), 0)
        self.assertEqual(self.summaries(),
                         {42: "chapter 42's summary", 43: "chapter 43's summary"},
                         "nothing moved, so nothing landed where gc could reap it")

    def test_a_stub_chapter_does_not_block_the_book(self):
        """A canonised chapter with no words yet has a manifest entry and no
        chunks. That is the healthy direction and must not stop a real move."""
        self.seed_summary(40, "A", "cu_a")
        self.manifest({41: "cu_a", 42: "cu_stub"}, indexed=[41])
        self.assertEqual(reposition_renumbered_chapters(self.db, None), 1)
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

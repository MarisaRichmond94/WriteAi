"""Tests for dirty_desynced_rows — the post-ingest sweep that catches
enrichment rows neither reposition nor GC can fix.

A row that is unstamped, or stamped with a cuid its book's manifest puts at a
different number, is the residue of a run that raced a renumbering (the
2026-08-12 incident): reposition refuses to move it, gc_orphans cannot collect
it (its number exists), and the identity-keyed cache believes its chapter is
done. The sweep deletes the chapter's enrich_state scope so the next run
regenerates it from current prose.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_enrich_desync_sweep -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import enrich  # noqa: E402
from server.enrich import dirty_desynced_rows, ensure_tables  # noqa: E402


class DesyncSweep(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        ensure_tables(self.db)
        self.db.execute("""CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY,
                           book_number INTEGER, chapter_number INTEGER)""")
        self.db.commit()
        self.addCleanup(enrich.forget_loom_ids)

    def manifest(self, numbers_to_ids, indexed=None):
        """Pretend book 2's manifest maps these numbers to cuids, with the
        indexed prose matching unless `indexed` says otherwise."""
        enrich.forget_loom_ids()
        enrich._LOOM_ID_CACHE[2] = ("bk", "sr", dict(numbers_to_ids))
        numbers = sorted(numbers_to_ids) if indexed is None else sorted(indexed)
        self.db.execute("DELETE FROM chunks")
        self.db.executemany("INSERT INTO chunks VALUES (?, 2, ?)",
                            [(f"c{n}", n) for n in numbers])
        self.db.commit()

    def seed_summary(self, chapter, summary, cuid):
        self.db.execute(
            "INSERT INTO chapter_summaries (book_number, chapter_number, "
            "summary, loom_chapter_id) VALUES (2,?,?,?)",
            (chapter, summary, cuid))
        self.db.commit()

    def seed_state(self, scope, content_hash="h"):
        self.db.execute(
            "INSERT INTO enrich_state (scope, content_hash) VALUES (?,?)",
            (scope, content_hash))
        self.db.commit()

    def scopes(self):
        return {r[0] for r in self.db.execute("SELECT scope FROM enrich_state")}

    def test_unstamped_row_is_dirtied(self):
        self.manifest({40: "cu_a"})
        self.seed_summary(40, "shifted", None)
        self.seed_state("events:cu_a")
        self.assertEqual(dirty_desynced_rows(self.db, None), 1)
        self.assertEqual(self.scopes(), set())

    def test_mis_stamped_row_is_dirtied(self):
        """A row stamped with the cuid the manifest puts at a DIFFERENT
        number would normally be repositioned — but when reposition refuses
        (duplicate stamps), the sweep must still flag it."""
        self.manifest({40: "cu_a", 41: "cu_b"})
        self.seed_summary(40, "actually chapter 41's", "cu_b")
        self.seed_summary(41, "also claims 41", "cu_b")
        self.seed_state("events:cu_a")
        self.assertEqual(dirty_desynced_rows(self.db, None), 1)
        self.assertNotIn("events:cu_a", self.scopes())

    def test_correctly_stamped_row_is_left_alone(self):
        self.manifest({40: "cu_a"})
        self.seed_summary(40, "fine", "cu_a")
        self.seed_state("events:cu_a")
        self.assertEqual(dirty_desynced_rows(self.db, None), 0)
        self.assertEqual(self.scopes(), {"events:cu_a"})

    def test_numeric_fallback_scope_is_dirtied_too(self):
        """Rows from before the book's first export hold number-keyed scopes;
        both keying schemes must be cleared or the stale one still hits."""
        self.manifest({40: "cu_a"})
        self.seed_summary(40, "shifted", None)
        self.seed_state("events:cu_a")
        self.seed_state("events:2.40")
        dirty_desynced_rows(self.db, None)
        self.assertEqual(self.scopes(), set())

    def test_unstamped_events_dirty_their_chapter(self):
        self.manifest({40: "cu_a"})
        self.db.execute(
            """INSERT INTO events (book_number, chapter_number, position,
                   title, type, granularity, loom_chapter_id)
               VALUES (2, 40, 0, 'stale', 'other', 'scene', NULL)""")
        self.db.commit()
        self.seed_state("events:cu_a")
        self.assertEqual(dirty_desynced_rows(self.db, None), 1)
        self.assertEqual(self.scopes(), set())

    def test_book_with_no_manifest_is_left_alone(self):
        """A never-exported book is legitimately unstamped — events_scope
        keys it by number and the ordinary hash mismatch covers it."""
        self.seed_summary(40, "fine", None)
        enrich._LOOM_ID_CACHE.clear()
        enrich._LOOM_ID_CACHE[2] = (None, None, {})
        self.seed_state("events:2.40")
        self.assertEqual(dirty_desynced_rows(self.db, None), 0)
        self.assertEqual(self.scopes(), {"events:2.40"})

    def test_manifest_behind_prose_blocks_the_sweep(self):
        """Stamps cannot be judged against a manifest that does not describe
        the indexed prose — the same gate reposition uses (LOOM-100)."""
        self.manifest({40: "cu_a"}, indexed=[40, 41])
        self.seed_summary(40, "unstamped but unjudgeable", None)
        self.seed_state("events:cu_a")
        self.assertEqual(dirty_desynced_rows(self.db, None), 0)
        self.assertEqual(self.scopes(), {"events:cu_a"})

    def test_chapter_the_manifest_does_not_know_is_ignored(self):
        """A row at a number outside the manifest is gc_orphans's problem,
        not an identity mismatch."""
        self.manifest({40: "cu_a"})
        self.seed_summary(99, "orphan", None)
        self.assertEqual(dirty_desynced_rows(self.db, None), 0)

    def test_db_with_no_chunks_table_is_a_noop(self):
        db = sqlite3.connect(":memory:")
        ensure_tables(db)
        self.assertEqual(dirty_desynced_rows(db, None), 0)


if __name__ == "__main__":
    unittest.main()

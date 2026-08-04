"""A cached chapter-identity map must not outlive the manifest it came from.

LOOM-98. `_LOOM_ID_CACHE` held a book's number->cuid map for the life of the
process. That map is the only thing that says which chapter a NUMBER means, so
when canonising a bonus chapter renumbered book 3 and rewrote the manifest, the
running server kept answering from the map it had resolved before the change.
Enrichment then wrote correct summaries stamped with the cuids of the chapters
they had displaced — 56 chapters whose text and identity disagreed.

Nothing downstream could tell. `reposition_renumbered_chapters` moved the rows
so that number and id agreed again, which is the only relation any consistency
check inspects. Only text-vs-identity was wrong, and nothing compares those.

These tests drive the real manifest reader against real files on disk, because
the bug lived precisely in the gap between "what the file says" and "what we
remembered it said".

Run from the repo root:
    .venv/bin/python -m unittest tests.test_loom_identity_freshness -v
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import enrich  # noqa: E402
from server.enrich import (ensure_tables, identity_matches_prose,  # noqa: E402
                           _loom_ids)


class ManifestFixture(unittest.TestCase):
    """A real book folder with a real manifest sidecar."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in self.dir.iterdir()]
                        and None)
        self.addCleanup(enrich.forget_loom_ids)
        self.resolves = []
        self.write_manifest({0: "cu_prologue", 12: "cu_l", 13: "cu_m", 14: "cu_n"})

    def write_manifest(self, numbers_to_ids):
        """Write the sidecar the way Loom does — atomically, via rename."""
        doc = {"manifestVersion": 1, "bookId": "BOOK3", "seriesId": "SERIES",
               "chapters": [{"id": cuid, "number": n, "label": str(n)}
                            for n, cuid in sorted(numbers_to_ids.items())]}
        path = self.dir / "B3.manifest.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc), encoding="utf-8")
        os.replace(tmp, path)
        # Loom's exports are seconds apart at minimum; the stat signature is
        # (mtime_ns, size), and forcing a distinct mtime here keeps the test
        # honest on filesystems that would otherwise collapse two writes in the
        # same tick into one signature.
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        return path

    def discovery(self):
        """Patch discovery, counting how often the directory walk happens."""
        book = types.SimpleNamespace(number=3, title="B3", folder=self.dir,
                                     loom_book_id="BOOK3",
                                     loom_series_id="SERIES")

        def counted(_cfg):
            self.resolves.append(1)
            return [book]

        return mock.patch("src.discovery.discover_books", side_effect=counted)


class CacheFreshness(ManifestFixture):

    def test_an_unchanged_manifest_is_resolved_once(self):
        """The saving the cache exists for: a stat per call, not a walk."""
        with self.discovery():
            for _ in range(5):
                self.assertEqual(_loom_ids(None, 3, 13)[2], "cu_m")
        self.assertEqual(len(self.resolves), 1)

    def test_a_rewritten_manifest_is_picked_up(self):
        """The incident. Canonising inserts a chapter at 13: what was 13 is now
        14, and the map must say so before anything is stamped with it."""
        with self.discovery():
            self.assertEqual(_loom_ids(None, 3, 13)[2], "cu_m")
            self.write_manifest({0: "cu_prologue", 12: "cu_l", 13: "cu_NEW",
                                 14: "cu_m", 15: "cu_n"})
            self.assertEqual(_loom_ids(None, 3, 13)[2], "cu_NEW",
                             "chapter 13 is the newly canonised chapter")
            self.assertEqual(_loom_ids(None, 3, 14)[2], "cu_m",
                             "what used to be 13 has moved to 14")
        self.assertEqual(len(self.resolves), 2, "exactly one re-resolve")

    def test_an_unreadable_manifest_keeps_the_cached_map(self):
        """Loom renames the manifest into place, so it briefly does not exist.
        A transient miss must never poison the run — the contract
        test_loom_identity_cache pins for the book-level resolver."""
        with self.discovery():
            self.assertEqual(_loom_ids(None, 3, 13)[2], "cu_m")
            (self.dir / "B3.manifest.json").unlink()
            self.assertEqual(_loom_ids(None, 3, 13)[2], "cu_m",
                             "the rename window is not a change")
        self.assertEqual(len(self.resolves), 1, "and costs no re-resolve")

    def test_a_seeded_cache_entry_is_trusted(self):
        """Callers (and every existing test) seed _LOOM_ID_CACHE directly. With
        no stamp to compare against, the cache is all there is."""
        enrich.forget_loom_ids()
        enrich._LOOM_ID_CACHE[3] = ("BOOK3", "SERIES", {13: "seeded"})
        with self.discovery():
            self.assertEqual(_loom_ids(None, 3, 13)[2], "seeded")
        self.assertEqual(len(self.resolves), 0)

    def test_forget_loom_ids_drops_the_stamp_too(self):
        """A cleared cache that left its stamp behind would let the next
        resolve be validated against a manifest it never read."""
        with self.discovery():
            _loom_ids(None, 3, 13)
            enrich.forget_loom_ids(3)
            self.assertNotIn(3, enrich._LOOM_ID_STAMP)
            _loom_ids(None, 3, 13)
        self.assertEqual(len(self.resolves), 2)


class IdentityMatchesProse(ManifestFixture):

    def db_with_chapters(self, numbers):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        ensure_tables(db)
        db.execute("""CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY,
                      book_number INTEGER, chapter_number INTEGER)""")
        db.executemany("INSERT INTO chunks VALUES (?, 3, ?)",
                       [(f"c{n}", n) for n in numbers])
        db.commit()
        return db

    def test_prose_the_manifest_has_never_heard_of_blocks_stamping(self):
        """The incident's detectable half: the export lags the prose, so the
        index holds a chapter number the manifest does not describe. Stamping
        from that map is what divorced text from identity."""
        db = self.db_with_chapters([0, 12, 13, 14, 15])
        with self.discovery():
            self.assertFalse(identity_matches_prose(db, None, 3))

    def test_a_manifest_ahead_of_the_prose_is_fine(self):
        """A canonised chapter with no words yet is a stub: a manifest entry
        and no chunks. That is the healthy direction and must not block."""
        db = self.db_with_chapters([0, 12, 13])
        with self.discovery():
            self.assertTrue(identity_matches_prose(db, None, 3))

    def test_an_exact_match_stamps(self):
        db = self.db_with_chapters([0, 12, 13, 14])
        with self.discovery():
            self.assertTrue(identity_matches_prose(db, None, 3))

    def test_a_book_with_no_manifest_does_not_stamp(self):
        db = self.db_with_chapters([0, 12])
        book = types.SimpleNamespace(number=3, title="B3", folder=self.dir,
                                     loom_book_id=None, loom_series_id=None)
        with mock.patch("src.discovery.discover_books", return_value=[book]):
            self.assertFalse(identity_matches_prose(db, None, 3),
                             "no identity to stamp with")

    def test_a_database_with_no_chunks_table_is_not_blocked(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        ensure_tables(db)
        with self.discovery():
            self.assertTrue(identity_matches_prose(db, None, 3))


if __name__ == "__main__":
    unittest.main()

"""Identity resolution must not cache a miss (KAN-12 / KAN-24).

Loom's canon export writes the manifest atomically — temp file, then rename —
so there is a window where it does not exist. A discovery pass landing in that
window resolves the book to None. Caching that turned a TRANSIENT miss into a
permanent one for the rest of the ingest: every chunk written afterwards
silently lost its stable id.

Observed in production: Marisa edited chapter 27 of The Secrets We Keep while
an ingest was running. The export raced the scan, and those two chunks were the
only ones in the entire database written without a loom_book_id. It went
unnoticed because a missing manifest is a legitimate state (a book never
canon-exported) and therefore does not warn.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_loom_identity_cache -v
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage import SeriesStore  # noqa: E402


def book(number, loom_book_id):
    return types.SimpleNamespace(number=number, title=f"B{number}",
                                 loom_book_id=loom_book_id,
                                 loom_series_id="SERIES" if loom_book_id else None)


class LoomIdentityCacheTest(unittest.TestCase):
    def store(self):
        s = SeriesStore.__new__(SeriesStore)
        s._cfg = object()
        s._loom_id_map = None
        return s

    def test_resolves_normally(self):
        s = self.store()
        with mock.patch("src.discovery.discover_books", return_value=[book(3, "L3")]):
            self.assertEqual(s._loom_identity(3), ("L3", "SERIES"))

    def test_a_miss_is_retried_not_cached(self):
        """The production bug: a transient miss must not poison the run."""
        s = self.store()
        calls = []

        def flaky(_cfg):
            calls.append(1)
            # first pass races the atomic rename and sees no manifest
            return [book(3, None)] if len(calls) == 1 else [book(3, "L3")]

        with mock.patch("src.discovery.discover_books", side_effect=flaky):
            first = s._loom_identity(3)
            second = s._loom_identity(3)

        self.assertEqual(first, (None, None), "the racing pass legitimately misses")
        self.assertEqual(second, ("L3", "SERIES"), "the next write must recover")
        self.assertEqual(len(calls), 2, "a miss must trigger a re-resolve")

    def test_a_hit_is_cached(self):
        """Re-resolving on every chunk would be a directory walk per chunk."""
        s = self.store()
        calls = []

        def counted(_cfg):
            calls.append(1)
            return [book(3, "L3")]

        with mock.patch("src.discovery.discover_books", side_effect=counted):
            for _ in range(5):
                s._loom_identity(3)
        self.assertEqual(len(calls), 1, "a resolved book should resolve once")

    def test_discovery_raising_is_survivable(self):
        s = self.store()
        with mock.patch("src.discovery.discover_books", side_effect=OSError("boom")):
            self.assertEqual(s._loom_identity(3), (None, None))

    def test_unknown_book_number_returns_none(self):
        s = self.store()
        with mock.patch("src.discovery.discover_books", return_value=[book(1, "L1")]):
            self.assertEqual(s._loom_identity(99), (None, None))


if __name__ == "__main__":
    unittest.main()

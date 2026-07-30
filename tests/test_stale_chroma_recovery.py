"""Regression tests for the stale Chroma handle that kept killing retrieval.

A re-ingest subprocess rewrites the on-disk Chroma segments underneath this
process's cached PersistentClient. The cached client keeps serving its now
inconsistent in-memory view and every query fails with:

    chromadb.errors.InternalError: Error executing plan: Internal error:
    Error finding id

AppState.reload_index() handles the re-ingests this server starts, but not one
run from the CLI, and not a reload that lands mid-query. Between 2026-07-22 and
2026-07-29 this fired 24 times, four of them during a review — where it is
caught and degraded to "no prior-context excerpts", so the writer got weaker
feedback with nothing in the UI to say so.

SeriesStore now reopens the collection and retries once, which turns a dead
query into a slow one.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_stale_chroma_recovery -v
"""

from __future__ import annotations

import unittest

from src.storage import SeriesStore

STALE = "Error executing plan: Internal error: Error finding id"

_HIT = {"ids": [["c1"]], "documents": [["chapter text"]],
        "metadatas": [[{"book_number": 1}]], "distances": [[0.12]]}


class _Collection:
    """Raises the stale-handle error for its first `fail_times` queries."""

    def __init__(self, fail_times: int = 0, error: str = STALE):
        self.fail_times, self.error, self.queries = fail_times, error, 0

    def query(self, **_kw):
        self.queries += 1
        if self.queries <= self.fail_times:
            raise RuntimeError(self.error)
        return _HIT


class _Store(SeriesStore):
    """SeriesStore without the filesystem: __init__ is bypassed and only the
    Chroma-handle plumbing under test is wired up."""

    def __init__(self, collection, reopen_to=None):
        self.collection = collection
        self._reopen_to = reopen_to
        self._notes_collection = object()
        self.reopens = 0

    def _open_chroma(self):
        self.reopens += 1
        if self._reopen_to is not None:
            self.collection = self._reopen_to


class StaleChromaRecoveryTest(unittest.TestCase):
    def test_stale_handle_reopens_and_retries(self):
        healthy = _Collection()
        store = _Store(_Collection(fail_times=1), reopen_to=healthy)

        hits = store.semantic_search([0.0, 0.1], top_k=3)

        self.assertEqual(store.reopens, 1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["chunk_id"], "c1")

    def test_reopen_drops_the_notes_collection_too(self):
        """The companion notes index is opened off the same client, so a
        reopen must not leave the old handle behind."""
        store = _Store(_Collection(fail_times=1), reopen_to=_Collection())
        store.semantic_search([0.0, 0.1], top_k=3)
        self.assertIsNone(store._notes_collection)

    def test_healthy_query_never_reopens(self):
        store = _Store(_Collection())
        store.semantic_search([0.0, 0.1], top_k=3)
        self.assertEqual(store.reopens, 0)

    def test_retry_happens_once_not_in_a_loop(self):
        """If the collection is broken on disk, reopening cannot fix it — the
        second failure must surface rather than spin."""
        broken = _Collection(fail_times=99)
        store = _Store(broken, reopen_to=broken)

        with self.assertRaises(RuntimeError):
            store.semantic_search([0.0, 0.1], top_k=3)

        self.assertEqual(store.reopens, 1)
        self.assertEqual(broken.queries, 2)

    def test_unrelated_errors_are_not_swallowed(self):
        """Only the stale-handle signature gets the retry; a real bug must not
        be masked by a reopen."""
        store = _Store(_Collection(fail_times=1, error="disk I/O error"))

        with self.assertRaises(RuntimeError) as ctx:
            store.semantic_search([0.0, 0.1], top_k=3)

        self.assertIn("disk I/O error", str(ctx.exception))
        self.assertEqual(store.reopens, 0)


if __name__ == "__main__":
    unittest.main()

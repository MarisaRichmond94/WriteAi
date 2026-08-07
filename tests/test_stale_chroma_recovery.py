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

import shutil
import tempfile
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
        # Mirrors the real one, which drops both handles via close_chroma.
        # RealChromaReopenTest is what holds this stub to that contract.
        self._notes_collection = None
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


class RealChromaReopenTest(unittest.TestCase):
    """The tests above stub `_open_chroma`, so they prove the retry MECHANISM
    and nothing about whether reopening reopens anything. It doesn't, by
    default: chroma caches System instances per path, so a second
    PersistentClient on an open path returns the first one's System — same Rust
    bindings, same stale segment view. Every recovery path in this file was
    therefore a no-op against the failure it was written for, and `Error
    finding id` survived until the process restarted (2026-08-07).

    These tests drive the real chromadb, which is the only way to catch that.
    """

    def _store(self, path):
        """A SeriesStore with only the Chroma plumbing wired up — __init__
        wants a Config, a books dir and SQLite, none of which this needs."""
        store = SeriesStore.__new__(SeriesStore)
        store._chroma_dir = path
        store._collection_name = "test-collection"
        store._legacy_collection_name = "test-collection"
        store._notes_collection = None
        return store

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="chroma-reopen-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_reopen_actually_rebinds_to_disk(self):
        """THE REGRESSION: before the fix both opens shared one System."""
        store = self._store(self.dir)
        store._open_chroma()
        first = store._chroma._system

        store._open_chroma()

        self.assertIsNot(store._chroma._system, first,
                         "reopen returned the cached System — the stale handle "
                         "would survive, and so would the failing query")

    def test_close_evicts_even_when_refcounts_leaked(self):
        """close() alone only drops the System at refcount zero, and the count
        leaks: every client construction adds to it and discarded stores never
        closed theirs. close_chroma must evict regardless."""
        import chromadb
        from chromadb.api.shared_system_client import SharedSystemClient

        store = self._store(self.dir)
        store._open_chroma()
        identifier = store._chroma._identifier
        # Stand-ins for the stores earlier reopens dropped without closing.
        leaked = [chromadb.PersistentClient(path=self.dir) for _ in range(3)]

        store.close_chroma()

        self.assertNotIn(identifier, SharedSystemClient._identifier_to_system)
        del leaked

    def test_reopened_collection_is_queryable(self):
        """A reopen that rebinds but can't serve a query has moved the failure,
        not fixed it."""
        store = self._store(self.dir)
        store._open_chroma()
        store.collection.upsert(ids=["c1"], embeddings=[[0.1, 0.2, 0.3]],
                                documents=["chapter text"])

        store._open_chroma()
        hits = store.semantic_search([0.1, 0.2, 0.3], top_k=1)

        self.assertEqual([h["chunk_id"] for h in hits], ["c1"])

    def test_reopen_drops_the_real_notes_handle(self):
        """The stubbed twin of this test can only assert what the stub does.
        The notes index is opened off the same client, so a handle kept across
        a reopen would be stale in exactly the same way."""
        store = self._store(self.dir)
        store._open_chroma()
        self.assertIsNotNone(store.notes)   # force the lazy open

        store._open_chroma()

        self.assertIsNone(store._notes_collection)

    def test_close_is_idempotent_and_safe_before_any_open(self):
        """`_open_chroma` calls it unconditionally, including the first time,
        and a failed close must never propagate into a request."""
        store = self._store(self.dir)
        store.close_chroma()          # never opened
        store._open_chroma()
        store.close_chroma()
        store.close_chroma()          # already closed
        self.assertIsNone(store._chroma)


if __name__ == "__main__":
    unittest.main()

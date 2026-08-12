"""The digest pipeline must fail SAFE and refresh ITSELF.

Lookup: any doubt about a stored digest means falling back to the full bible
(a bigger prompt), never a thinner review — absent table, absent row, and a
stale input_hash must all return None rather than raise or serve stale
context.

Refresh: the enrichment run re-checks every book on every run, so the loop's
hash guard is what keeps that free — a fresh book must cost zero API calls,
a changed source must trigger exactly one rebuild, and one book's failure
must not stop the others.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_book_digests -v
"""

from __future__ import annotations

import hashlib
import sqlite3
import unittest
from types import SimpleNamespace

from server.digests import DIGESTS_DDL, lookup_digest, refresh_digests


def _store(db, book: int, source_md: str, digest_md: str) -> None:
    db.execute(DIGESTS_DDL)
    db.execute(
        "INSERT OR REPLACE INTO book_digests "
        "(book_number, input_hash, digest_md, model, created_at) "
        "VALUES (?, ?, ?, 'test-model', '2026-08-12')",
        (book, hashlib.sha256(source_md.encode("utf-8")).hexdigest(),
         digest_md))


class LookupDigest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")

    def test_fresh_digest_is_returned(self):
        _store(self.db, 2, "## Chapter 1\nsource text", "condensed digest")
        self.assertEqual(
            lookup_digest(self.db, 2, "## Chapter 1\nsource text"),
            "condensed digest")

    def test_changed_source_retires_the_digest(self):
        """Re-enrichment rewrites chapter summaries; the stored digest no
        longer describes them and must not be served."""
        _store(self.db, 2, "## Chapter 1\nsource text", "condensed digest")
        self.assertIsNone(
            lookup_digest(self.db, 2, "## Chapter 1\nREWRITTEN summaries"))

    def test_missing_book_returns_none(self):
        _store(self.db, 2, "src", "digest")
        self.assertIsNone(lookup_digest(self.db, 3, "src"))

    def test_missing_table_returns_none(self):
        """The read path must not require a refresh to have ever run — a
        store predating the feature serves full bibles, not a 500."""
        self.assertIsNone(lookup_digest(self.db, 1, "anything"))


class _FakeClient:
    """Counts calls; returns a fixed digest body with usage numbers."""

    def __init__(self, body: str = "## Synopsis\nThings happen."):
        self.calls = 0
        self.messages = self

    def create(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            content=[SimpleNamespace(type="text",
                                     text="## Synopsis\nThings happen.")],
            usage=SimpleNamespace(input_tokens=100, output_tokens=50))


class RefreshDigests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE chunks (book_number INTEGER, "
                        "book_title TEXT)")
        self.db.execute("INSERT INTO chunks VALUES (1, 'First Book')")
        self.cfg = SimpleNamespace(extraction_model="claude-haiku-4-5",
                                   cost_log_enabled=False)
        self.client = _FakeClient()

    def _refresh(self, source: str, **kw):
        return refresh_digests(self.db, self.cfg, self.client, [1],
                               source_for=lambda b: source, **kw)

    def test_stale_book_is_built_once_then_skipped(self):
        stats = self._refresh("source v1")
        self.assertEqual((stats["built"], self.client.calls), (1, 1))
        # same source again: the hash guard must make this free
        stats = self._refresh("source v1")
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(self.client.calls, 1, "fresh book hit the API")
        # and the stored digest is now servable at that hash
        self.assertIn("First Book", lookup_digest(self.db, 1, "source v1"))

    def test_changed_source_rebuilds(self):
        self._refresh("source v1")
        stats = self._refresh("source v2")
        self.assertEqual(stats["built"], 1)
        self.assertEqual(self.client.calls, 2)
        self.assertIsNone(lookup_digest(self.db, 1, "source v1"),
                          "old-hash lookup must not serve the new digest")

    def test_one_books_failure_does_not_stop_the_others(self):
        self.db.execute("INSERT INTO chunks VALUES (2, 'Second Book')")

        def source_for(book):
            if book == 1:
                raise RuntimeError("summaries unreadable")
            return "book 2 source"

        stats = refresh_digests(self.db, self.cfg, self.client, [1, 2],
                                source_for=source_for)
        self.assertEqual((stats["failed"], stats["built"]), (1, 1))
        self.assertIsNotNone(lookup_digest(self.db, 2, "book 2 source"))

    def test_force_rebuilds_a_fresh_digest(self):
        self._refresh("source v1")
        stats = self._refresh("source v1", force=True)
        self.assertEqual(stats["built"], 1)
        self.assertEqual(self.client.calls, 2)


if __name__ == "__main__":
    unittest.main()

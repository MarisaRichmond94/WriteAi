"""Unit tests for stable Loom identity on discovered books (KAN-12).

`Book.number` and `Book.title` are both derived from the folder name, so
neither identifies a book across edits: `number` survives a rename but breaks
on insertion or reordering, `title` does the reverse. `loom_book_id` comes from
the manifest sidecar and survives both.

The degraded paths matter as much as the happy one. Discovery runs on every
sync, so a missing or corrupt manifest must never raise — it falls back to
number/title matching, which is what the code did before this change.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_discovery_identity -v
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# src.discovery imports SUPPORTED_SUFFIXES from src.parser, which drags in the
# heavy parsing stack. Stub it — these tests only exercise folder walking.
_parser = types.ModuleType("src.parser")
_parser.SUPPORTED_SUFFIXES = {".txt", ".docx", ".pages", ".md", ".pdf"}
sys.modules.setdefault("src.parser", _parser)

from src.discovery import discover_books  # noqa: E402

PREFIX = re.compile(r"^\d+\.\s*")


def make_book(root: Path, number: int, title: str, manifest: dict | str | None):
    """Create '<number>. <title>/' with a manuscript and optional manifest.

    `manifest` may be a dict (written as JSON), a raw string (to inject
    malformed content), or None (no sidecar at all).
    """
    folder = root / f"{number}. {title}"
    folder.mkdir()
    (folder / f"{title}.txt").write_text("prose", encoding="utf-8")
    if manifest is not None:
        body = manifest if isinstance(manifest, str) else json.dumps(manifest)
        (folder / f"{title}.manifest.json").write_text(body, encoding="utf-8")
    return folder


def discover(root: Path):
    return discover_books(types.SimpleNamespace(books_dir=root,
                                                book_prefix_pattern=PREFIX))


class DiscoveryIdentityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_reads_ids_from_manifest(self):
        make_book(self.root, 1, "Ghost", {
            "manifestVersion": 1, "bookId": "bk_abc", "seriesId": "sr_xyz"})
        (book,) = discover(self.root)
        self.assertEqual(book.loom_book_id, "bk_abc")
        self.assertEqual(book.loom_series_id, "sr_xyz")

    def test_missing_manifest_yields_none(self):
        make_book(self.root, 1, "Ghost", None)
        (book,) = discover(self.root)
        self.assertIsNone(book.loom_book_id)
        self.assertIsNone(book.loom_series_id)
        # still discovered — identity is unknown, not fatal
        self.assertEqual(book.number, 1)
        self.assertEqual(book.title, "Ghost")

    def test_malformed_manifest_does_not_raise(self):
        make_book(self.root, 1, "Ghost", "{not valid json")
        (book,) = discover(self.root)
        self.assertIsNone(book.loom_book_id)

    def test_manifest_without_book_id(self):
        make_book(self.root, 1, "Ghost", {"manifestVersion": 1})
        (book,) = discover(self.root)
        self.assertIsNone(book.loom_book_id)

    def test_empty_string_id_is_normalised_to_none(self):
        """Falsy-but-present must not be mistaken for a real identity."""
        make_book(self.root, 1, "Ghost", {"bookId": "", "seriesId": ""})
        (book,) = discover(self.root)
        self.assertIsNone(book.loom_book_id)
        self.assertIsNone(book.loom_series_id)

    def test_identity_survives_a_rename(self):
        """The whole point: same book, renamed folder and title, same cuid."""
        make_book(self.root, 1, "Ghost", {"bookId": "bk_abc", "seriesId": "sr_xyz"})
        (before,) = discover(self.root)

        renamed = Path(self._tmp.name) / "renamed"
        renamed.mkdir()
        make_book(renamed, 1, "Ghost Story", {"bookId": "bk_abc", "seriesId": "sr_xyz"})
        (after,) = discover(renamed)

        self.assertNotEqual(before.title, after.title)
        self.assertEqual(before.loom_book_id, after.loom_book_id)

    def test_identity_survives_reordering(self):
        """Positional keys break on insertion; the cuid does not."""
        make_book(self.root, 2, "Ghost", {"bookId": "bk_abc", "seriesId": "sr_xyz"})
        (before,) = discover(self.root)

        reordered = Path(self._tmp.name) / "reordered"
        reordered.mkdir()
        make_book(reordered, 3, "Ghost", {"bookId": "bk_abc", "seriesId": "sr_xyz"})
        (after,) = discover(reordered)

        self.assertNotEqual(before.number, after.number)
        self.assertEqual(before.loom_book_id, after.loom_book_id)

    def test_ids_are_unique_across_a_series(self):
        for n, t in ((1, "One"), (2, "Two"), (3, "Three")):
            make_book(self.root, n, t, {"bookId": f"bk_{n}", "seriesId": "sr_xyz"})
        books = discover(self.root)
        ids = [b.loom_book_id for b in books]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual({b.loom_series_id for b in books}, {"sr_xyz"})


if __name__ == "__main__":
    unittest.main()

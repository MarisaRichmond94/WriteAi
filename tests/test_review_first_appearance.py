"""The first-appearance gate: a character the reader has not met yet must
never get a profile in the review's bible block.

Profiles distill whole books, so on the very chapter that introduces a
character every profile line is future material — reviewers were reading it
as "the reader already knows this character" and calling the introduction a
rehash (2026-09-20 Bri/Austin reviews). With reader_upto set, _build_bible
replaces such a profile with an explicit first-appearance marker; without
it (downloadable bible, Explore chat) nothing changes.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_review_first_appearance -v
"""

from __future__ import annotations

import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server.routers.books import _build_bible


def _entity(name: str, chunk_ids: list[str], aliases=()):
    return SimpleNamespace(name=name, kind="character",
                           aliases=list(aliases), chunk_ids=set(chunk_ids))


class FirstAppearanceGate(unittest.TestCase):
    """Book 2 under review. Jared is on the page from chapter 1; Bri first
    steps on the page in chapter 8; Zed not until chapter 12; Austin has
    book-1 presence but first appears in book 2 at chapter 8."""

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE chunks (chunk_id TEXT, "
                        "book_number INTEGER, book_title TEXT, "
                        "chapter_number INTEGER, chunk_index INTEGER "
                        "DEFAULT 0, metadata_json TEXT)")
        self.db.execute("CREATE TABLE character_profiles (name TEXT, "
                        "traits_json TEXT, relationships_json TEXT, "
                        "arcs_json TEXT)")
        chunk_meta: dict[str, tuple] = {}

        def chunk(cid: str, book: int, ch: int):
            self.db.execute("INSERT INTO chunks VALUES (?, ?, 'Book Two', ?, "
                            "0, '{}')", (cid, book, ch))
            chunk_meta[cid] = (book, ch)

        for ch in range(1, 13):
            chunk(f"j{ch}", 2, ch)              # Jared everywhere
        for ch in (8, 9, 10):
            chunk(f"b{ch}", 2, ch)              # Bri from ch 8
            chunk(f"a{ch}", 2, ch)              # Austin from ch 8 in book 2
        chunk("a-b1", 1, 3)                     # …but present in book 1
        for ch in (12, 12, 12):
            chunk(f"z{ch}-{len(chunk_meta)}", 2, ch)   # Zed only at ch 12

        for name, arc in (("Jared Gatlin", "Jared spirals across the book."),
                          ("Brielle Draper", "Bri discovers Noah's trauma."),
                          ("Austin Kutchco", "Austin becomes a confidant."),
                          ("Zed Moray", "Zed emerges as a threat.")):
            self.db.execute(
                "INSERT INTO character_profiles VALUES (?, ?, '[]', ?)",
                (name, '["Loyal", "Guarded"]',
                 '{"2": "%s"}' % arc))

        entities = {
            "Jared Gatlin": _entity("Jared Gatlin",
                                    [f"j{c}" for c in range(1, 13)]),
            "Brielle Draper": _entity("Brielle Draper",
                                      ["b8", "b9", "b10"], aliases=["Bri"]),
            "Austin Kutchco": _entity("Austin Kutchco",
                                      ["a8", "a9", "a10", "a-b1"]),
            "Zed Moray": _entity("Zed Moray",
                                 [c for c in chunk_meta if c.startswith("z")]),
        }
        self.canon = SimpleNamespace(entities=entities, chunk_meta=chunk_meta,
                                     ensure_built=lambda: None,
                                     resolve=lambda n: None)
        self.s = SimpleNamespace(db=self.db, canon=self.canon)
        cast = ("Jared Gatlin faces Brielle Draper while Austin Kutchco and "
                "Zed Moray are named.")
        self.kw = dict(compact=True, characters=True, chapters=False,
                       mention_filter=cast)

    def _md(self, **kw):
        with patch("server.routers.books.writer_store.character_map",
                   return_value={}):
            _, md = _build_bible(self.s, 2, **{**self.kw, **kw})
        return md

    def _section(self, md: str, name: str) -> str:
        body = md.split(f"### {name}")[1]
        return body.split("###")[0]

    def test_first_appearance_gets_marker_not_profile(self):
        bri = self._section(self._md(reader_upto=8), "Brielle Draper")
        self.assertIn("FIRST APPEARANCE", bri)
        self.assertIn("never met this character", bri)
        self.assertNotIn("Traits", bri)
        self.assertNotIn("Noah's trauma", bri)

    def test_not_yet_on_page_gets_softer_future_marker(self):
        zed = self._section(self._md(reader_upto=8), "Zed Moray")
        self.assertIn("Not yet on the page", zed)
        self.assertNotIn("Zed emerges", zed)

    def test_earlier_book_presence_softens_the_marker(self):
        austin = self._section(self._md(reader_upto=8), "Austin Kutchco")
        self.assertIn("FIRST APPEARANCE", austin)
        self.assertIn("earlier books", austin)
        self.assertNotIn("never met", austin)
        self.assertNotIn("Traits", austin)

    def test_established_character_keeps_profile_with_honest_arc_label(self):
        jared = self._section(self._md(reader_upto=8), "Jared Gatlin")
        self.assertIn("Traits", jared)
        self.assertIn("Jared spirals", jared)
        self.assertIn("not reader knowledge", jared)
        self.assertNotIn("FIRST APPEARANCE", jared)

    def test_character_already_met_is_ungated_on_later_chapters(self):
        bri = self._section(self._md(reader_upto=9), "Brielle Draper")
        self.assertIn("Traits", bri)
        self.assertNotIn("FIRST APPEARANCE", bri)

    def test_no_reader_upto_keeps_legacy_bible_shape(self):
        md = self._md()
        self.assertNotIn("FIRST APPEARANCE", md)
        self.assertIn("**Arc in this book:**", md)
        self.assertIn("Noah's trauma", self._section(md, "Brielle Draper"))


if __name__ == "__main__":
    unittest.main()

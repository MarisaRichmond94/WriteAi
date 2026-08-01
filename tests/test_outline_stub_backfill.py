"""A stubbed chapter's card must stay blank (LOOM-64).

`get_outline` backfills a card's displayed summary from `chapter_summaries`,
which is keyed `(book_number, chapter_number)` and carries no chapter identity.
A stub inserted mid-book therefore lands on a number a DIFFERENT chapter used
to occupy, and without a guard the blank new card would render that chapter's
summary — describing a chapter that does not exist yet, in a card the writer
just created to plan one.

The guard keys on wordCount from the manifest, so it holds regardless of how
stale the summary table is. LOOM-65 fixes the underlying keying; this stays
correct either way, because a chapter with no words has no summary to show.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_outline_stub_backfill -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.routers import plan, sync  # noqa: E402


def manifest_chapter(num, loom_id, word_count):
    return {"id": loom_id, "number": num, "label": str(num), "pov": "Jared",
            "date": "Thursday, August 19th", "wordCount": word_count}


class StubBackfillTest(unittest.TestCase):
    def run_get_outline(self, cards, canon, prose, extracted):
        """get_outline against fakes — no filesystem, no real database."""
        store = {"BOOK3": cards}
        saved = []

        db = mock.Mock()
        db.execute.return_value = list(prose.items())

        with mock.patch.object(plan.outline_store, "load_outlines",
                               return_value=store), \
             mock.patch.object(plan.outline_store, "outline_key",
                               return_value="BOOK3"), \
             mock.patch.object(plan.outline_store, "save_outlines",
                               side_effect=lambda o: saved.append(o)), \
             mock.patch.object(plan, "get_state",
                               return_value=mock.Mock(db=db)), \
             mock.patch.object(plan, "_extracted_chapters",
                               return_value=extracted), \
             mock.patch.object(sync, "book_sync_state",
                               return_value=(True, canon)):
            return plan.get_outline(3)

    def test_a_stub_does_not_inherit_a_stale_summary(self):
        """The number 32 still has a summary row from whoever held it before
        the insert. The stub's card must ignore it."""
        canon = {31: manifest_chapter(31, "L31", 1200),
                 32: manifest_chapter(32, "LNEW", 0)}
        cards = [
            {"id": "ch-3-31", "book": 3, "chapter": 31, "position": 31.0,
             "status": "synced", "heading": "Chapter 31", "pov": "Jared",
             "date": "d", "writer_summary": "", "summary_source": None,
             "extracted_bullets": [], "notes": None, "loom_id": "L31"},
            {"id": "ch-3-32", "book": 3, "chapter": 32, "position": 32.0,
             "status": "synced", "heading": "Chapter 32", "pov": "Jared",
             "date": "d", "writer_summary": "", "summary_source": None,
             "extracted_bullets": [], "notes": None, "loom_id": "LNEW"},
        ]
        extracted = {31: {"chapter": 31, "heading": "Chapter 31", "pov": "Jared",
                          "date": "d", "bullets": []}}
        prose = {31: "Jared confronts Daniel.",
                 32: "STALE — belonged to the old chapter 32."}

        out = self.run_get_outline(cards, canon, prose, extracted)
        by_num = {c["chapter"]: c for c in out["chapters"]}

        self.assertEqual(by_num[32]["writer_summary"], "",
                         "a stub's card must stay blank")
        self.assertNotIn("STALE", by_num[32]["writer_summary"])
        # The written chapter beside it still backfills normally.
        self.assertIn("Jared confronts Daniel", by_num[31]["writer_summary"])

    def test_a_stub_that_gains_prose_backfills_normally(self):
        """The guard is about wordCount, not about the card being new."""
        canon = {32: manifest_chapter(32, "LNEW", 1500)}
        cards = [{"id": "ch-3-32", "book": 3, "chapter": 32, "position": 32.0,
                  "status": "synced", "heading": "Chapter 32", "pov": "Jared",
                  "date": "d", "writer_summary": "", "summary_source": None,
                  "extracted_bullets": [], "notes": None, "loom_id": "LNEW"}]
        extracted = {32: {"chapter": 32, "heading": "Chapter 32", "pov": "Jared",
                          "date": "d", "bullets": []}}

        out = self.run_get_outline(cards, canon, {32: "Now it is written."},
                                   extracted)
        self.assertIn("Now it is written.", out["chapters"][0]["writer_summary"])

    def test_writer_words_on_a_stub_survive(self):
        """Planning notes written into a stub's card are the whole point of
        having the card. Nothing may overwrite them."""
        canon = {32: manifest_chapter(32, "LNEW", 0)}
        cards = [{"id": "ch-3-32", "book": 3, "chapter": 32, "position": 32.0,
                  "status": "synced", "heading": "Chapter 32", "pov": "Jared",
                  "date": "d", "writer_summary": "<p>Emma finds the letter</p>",
                  "summary_source": None, "extracted_bullets": [],
                  "notes": "tie back to ch 12", "loom_id": "LNEW"}]

        out = self.run_get_outline(cards, canon, {32: "STALE"}, {})
        card = out["chapters"][0]
        self.assertEqual(card["writer_summary"], "<p>Emma finds the letter</p>")
        self.assertEqual(card["notes"], "tie back to ch 12")


if __name__ == "__main__":
    unittest.main()

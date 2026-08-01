"""Summaries follow their chapter, not its number (LOOM-65).

`chapter_summaries` was keyed (book_number, chapter_number) with nothing that
survives an insert. Inserting a chapter in Loom renumbers every later chapter,
and until the next enrichment run each renumbered chapter's row still sits
under its OLD number — so the outline backfill handed every card the summary of
whichever chapter used to hold its number. Enrichment is cost-gated and runs on
a cadence, so that window is days, not minutes.

`loom_chapter_id` makes the row say which chapter it describes. A missing id is
unknown identity and degrades to number matching, never to "no match".

Run from the repo root:
    .venv/bin/python -m unittest tests.test_chapter_summary_identity -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.routers import plan, sync  # noqa: E402


def chapter(num, loom_id, word_count=1200):
    return {"id": loom_id, "number": num, "label": str(num), "pov": "Jared",
            "date": "d", "wordCount": word_count}


def card(num, loom_id, summary="", source=None, notes=None, bullets=None):
    return {"id": f"ch-3-{num}", "book": 3, "chapter": num,
            "position": float(num), "status": "synced",
            "heading": f"Chapter {num}", "pov": "Jared", "date": "d",
            "writer_summary": summary, "summary_source": source,
            "extracted_bullets": bullets or [], "notes": notes,
            "loom_id": loom_id}


class SummaryIdentityTest(unittest.TestCase):
    def outline(self, cards, canon, rows, extracted=None):
        """get_outline against fakes. `rows` are (num, summary, loom_chapter_id)
        exactly as the query returns them."""
        store = {"BOOK3": cards}
        db = mock.Mock()
        db.execute.return_value = mock.Mock(fetchall=lambda: rows)

        with mock.patch.object(plan.outline_store, "load_outlines",
                               return_value=store), \
             mock.patch.object(plan.outline_store, "outline_key",
                               return_value="BOOK3"), \
             mock.patch.object(plan.outline_store, "save_outlines"), \
             mock.patch.object(plan, "get_state",
                               return_value=mock.Mock(db=db)), \
             mock.patch.object(plan, "_extracted_chapters",
                               return_value=extracted if extracted is not None
                               else {n: {"chapter": n, "heading": f"Chapter {n}",
                                         "pov": "Jared", "date": "d",
                                         "bullets": []} for n in canon}), \
             mock.patch.object(sync, "book_sync_state",
                               return_value=(True, canon)):
            out = plan.get_outline(3)
        return {c["chapter"]: c for c in out["chapters"]}

    def test_summary_follows_its_chapter_after_a_renumber(self):
        """The bug, directly. A chapter was inserted, so the chapter that used
        to be 30 is now 31 — but enrichment has not re-run, so its summary row
        still sits at 30. Matching by id must still find it."""
        canon = {30: chapter(30, "LNEW"), 31: chapter(31, "L30")}
        cards = [card(30, "LNEW"), card(31, "L30")]
        rows = [(30, "belongs to the chapter now numbered 31", "L30")]

        by_num = self.outline(cards, canon, rows)

        self.assertIn("now numbered 31", by_num[31]["writer_summary"])
        self.assertEqual(by_num[30]["writer_summary"], "",
                         "the inserted chapter has no summary and must not "
                         "borrow its neighbour's")

    def test_stamped_row_is_never_matched_by_number(self):
        """A row that names a different chapter must not be shown, even though
        its number lines up."""
        canon = {5: chapter(5, "LNEW")}
        cards = [card(5, "LNEW")]
        rows = [(5, "this is chapter 5's OLD occupant", "LOLD")]

        by_num = self.outline(cards, canon, rows)
        self.assertEqual(by_num[5]["writer_summary"], "")

    def test_unstamped_rows_still_match_by_number(self):
        """Legacy rows, and books never canon-exported, keep working exactly as
        before — a missing id is unknown identity, not 'no match'."""
        canon = {7: chapter(7, "L7")}
        cards = [card(7, "L7")]
        rows = [(7, "legacy summary", None)]

        by_num = self.outline(cards, canon, rows)
        self.assertIn("legacy summary", by_num[7]["writer_summary"])

    def test_half_migrated_book_keeps_rendering(self):
        """Enrichment stamps rows as it works through a book. A stamped row and
        an unstamped one must both land on the right card in the meantime."""
        canon = {1: chapter(1, "L1"), 2: chapter(2, "L2")}
        cards = [card(1, "L1"), card(2, "L2")]
        rows = [(1, "stamped one", "L1"), (2, "legacy two", None)]

        by_num = self.outline(cards, canon, rows)
        self.assertIn("stamped one", by_num[1]["writer_summary"])
        self.assertIn("legacy two", by_num[2]["writer_summary"])

    def test_unstamped_card_falls_back_to_number(self):
        """A card reconcile has not stamped yet (no manifest for the book) must
        not lose its summary."""
        canon = {4: chapter(4, "L4")}
        cards = [card(4, None)]
        rows = [(4, "summary four", None)]

        by_num = self.outline(cards, canon, rows)
        self.assertIn("summary four", by_num[4]["writer_summary"])

    def test_writer_words_are_never_overwritten(self):
        """The invariant, restated against the new lookup."""
        canon = {9: chapter(9, "L9")}
        cards = [card(9, "L9", summary="<p>MY OWN WORDS</p>", source="<p>x</p>")]
        rows = [(9, "machine summary", "L9")]

        by_num = self.outline(cards, canon, rows)
        self.assertEqual(by_num[9]["writer_summary"], "<p>MY OWN WORDS</p>")

    def test_falls_through_to_bullets_when_no_row_matches(self):
        canon = {3: chapter(3, "L3")}
        bullets = ["he arrives", "she leaves"]
        cards = [card(3, "L3", bullets=bullets)]
        rows = [(3, "another chapter's summary", "LOTHER")]
        # The index must agree about the bullets, or reconcile clears them as
        # stale before the backfill ever looks at the card.
        extracted = {3: {"chapter": 3, "heading": "Chapter 3", "pov": "Jared",
                         "date": "d", "bullets": bullets}}

        by_num = self.outline(cards, canon, rows, extracted=extracted)
        self.assertIn("he arrives", by_num[3]["writer_summary"])
        self.assertNotIn("another chapter", by_num[3]["writer_summary"])

    def test_missing_column_degrades_instead_of_failing(self):
        """An index that predates the migration must not 500 the outline."""
        canon = {1: chapter(1, "L1")}
        cards = [card(1, "L1", bullets=["a"])]
        store = {"BOOK3": cards}
        db = mock.Mock()
        db.execute.side_effect = Exception("no such column: loom_chapter_id")

        with mock.patch.object(plan.outline_store, "load_outlines",
                               return_value=store), \
             mock.patch.object(plan.outline_store, "outline_key",
                               return_value="BOOK3"), \
             mock.patch.object(plan.outline_store, "save_outlines"), \
             mock.patch.object(plan, "get_state",
                               return_value=mock.Mock(db=db)), \
             mock.patch.object(plan, "_extracted_chapters", return_value={}), \
             mock.patch.object(sync, "book_sync_state",
                               return_value=(True, canon)):
            out = plan.get_outline(3)
        self.assertEqual(len(out["chapters"]), 1)


class MigrationTest(unittest.TestCase):
    def test_migration_is_additive_and_idempotent(self):
        import sqlite3

        from src.storage import migrate_schema
        db = sqlite3.connect(":memory:")
        # migrate_schema's first loop ALTERs these unconditionally, so they have
        # to exist for it to run at all.
        for t in ("foreshadowing", "unresolved_questions", "character_knowledge"):
            db.execute(f"CREATE TABLE {t} (id INTEGER)")
        db.execute("""CREATE TABLE chapter_summaries (
                          book_number INTEGER NOT NULL,
                          chapter_number INTEGER NOT NULL,
                          summary TEXT NOT NULL,
                          PRIMARY KEY (book_number, chapter_number))""")
        db.execute("INSERT INTO chapter_summaries VALUES (1, 1, 'kept')")

        migrate_schema(db)
        migrate_schema(db)          # must be a no-op, not an error

        cols = {r[1] for r in db.execute(
            "SELECT * FROM pragma_table_info('chapter_summaries')")}
        self.assertIn("loom_chapter_id", cols)
        self.assertEqual(
            db.execute("SELECT summary, loom_chapter_id FROM chapter_summaries"
                       ).fetchone(), ("kept", None),
            "existing rows must survive with a NULL id")


if __name__ == "__main__":
    unittest.main()

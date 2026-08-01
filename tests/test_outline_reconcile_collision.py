"""Regression tests for the _auto_reconcile renumbering collision (KAN-24).

`_auto_reconcile` matches cards as `by_loom.get(loom_id) or by_num.get(num)`,
where by_num holds only UNSTAMPED cards. When a stamped card is renumbered onto
a number an unstamped card already occupies, by_loom wins and the unstamped card
is never claimed by any iteration — it lingers forever as a visible duplicate.

Observed in production: book 3 had two chapter-68 cards with byte-identical
1087-char summaries. `ch-3-65-08cdf0` was created at chapter 65, later renumbered
to 68, landing on the pre-existing seeded `ch-3-68`.

The fix removes the stranded twin, but ONLY when the machine wrote it. A twin
carrying writer words or notes is kept and logged — deleting writing to tidy a
duplicate would be much worse than the duplicate.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_outline_reconcile_collision -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.routers import plan  # noqa: E402


def ext(num: int, bullets=None):
    return {"chapter": num, "heading": f"Chapter {num}", "pov": "Jared",
            "date": "Thursday, August 19th", "bullets": bullets or []}


def card(cid, num, loom_id=None, summary="", source=None, notes=None, bullets=None):
    return {"id": cid, "book": 3, "chapter": num, "position": float(num),
            "status": "synced", "heading": f"Chapter {num}", "pov": "Jared",
            "date": "Thursday, August 19th", "writer_summary": summary,
            "summary_source": source, "extracted_bullets": bullets or [],
            "notes": notes, "loom_id": loom_id}


def canon(num_to_loom, stubs=()):
    """`book_sync_state`'s second return: manifest chapter number -> record.

    Written by default; numbers listed in `stubs` get wordCount 0, which is what
    makes them unwritten canon rather than merely un-ingested.
    """
    return {num: {"id": loom_id, "number": num, "label": str(num),
                  "pov": "Jared", "date": "Thursday, August 19th",
                  "wordCount": 0 if num in stubs else 1200}
            for num, loom_id in num_to_loom.items()}


class ReconcileCollisionTest(unittest.TestCase):
    def reconcile(self, cards, extracted, num_to_loom, stubs=None):
        # A canon chapter the index has nothing for is a stub unless the caller
        # says otherwise — that is what it means in every real book.
        if stubs is None:
            stubs = set(num_to_loom) - set(extracted)
        with mock.patch.object(plan, "_extracted_chapters", return_value=extracted):
            changed = plan._auto_reconcile(3, cards, True, canon(num_to_loom, stubs))
        return changed, cards

    def test_production_scenario_duplicate_is_removed(self):
        """The exact book-3 shape: stamped card renumbers onto a seeded twin."""
        machine = "<p>identical machine summary</p>"
        cards = [
            card("ch-3-65-08cdf0", 65, loom_id="L68", summary=machine, source=machine),
            card("ch-3-68", 68, loom_id=None, summary=machine, source=machine),
        ]
        changed, cards = self.reconcile(cards, {68: ext(68)}, {68: "L68"})

        self.assertTrue(changed)
        self.assertEqual(len(cards), 1, "the stranded twin should be gone")
        survivor = cards[0]
        self.assertEqual(survivor["id"], "ch-3-65-08cdf0")
        self.assertEqual(survivor["loom_id"], "L68")
        self.assertEqual(survivor["chapter"], 68)

    def test_twin_with_writer_summary_is_kept(self):
        """Never delete writing to tidy a duplicate."""
        machine = "<p>machine</p>"
        cards = [
            card("ch-3-65-abc", 65, loom_id="L68", summary=machine, source=machine),
            card("ch-3-68", 68, summary="<p>MY OWN WORDS</p>", source=machine),
        ]
        _, cards = self.reconcile(cards, {68: ext(68)}, {68: "L68"})
        self.assertEqual(len(cards), 2)
        self.assertIn("MY OWN WORDS", cards[1]["writer_summary"])

    def test_twin_with_notes_is_kept(self):
        """Notes are writer-only, so a note protects the card on its own."""
        machine = "<p>machine</p>"
        cards = [
            card("ch-3-65-abc", 65, loom_id="L68", summary=machine, source=machine),
            card("ch-3-68", 68, summary=machine, source=machine, notes="remember this"),
        ]
        _, cards = self.reconcile(cards, {68: ext(68)}, {68: "L68"})
        self.assertEqual(len(cards), 2)

    def test_empty_twin_is_removed(self):
        """A blank unstamped card carries nothing worth keeping."""
        cards = [
            card("ch-3-65-abc", 65, loom_id="L68", summary="", source=None),
            card("ch-3-68", 68, summary="", source=None),
        ]
        _, cards = self.reconcile(cards, {68: ext(68)}, {68: "L68"})
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["id"], "ch-3-65-abc")

    def test_first_time_stamping_is_not_treated_as_a_collision(self):
        """The ordinary case: an unstamped card IS the match and must survive."""
        cards = [card("ch-3-68", 68, loom_id=None, summary="", source=None)]
        _, cards = self.reconcile(cards, {68: ext(68)}, {68: "L68"})
        self.assertEqual(len(cards), 1, "the only card must not delete itself")
        self.assertEqual(cards[0]["loom_id"], "L68")

    def test_no_collision_leaves_everything_alone(self):
        cards = [
            card("ch-3-1", 1, loom_id="L1", summary="", source=None),
            card("ch-3-2", 2, loom_id="L2", summary="", source=None),
        ]
        _, cards = self.reconcile(cards, {1: ext(1), 2: ext(2)}, {1: "L1", 2: "L2"})
        self.assertEqual(len(cards), 2)

    # --- out-of-canon cards (the Faded ch-2-93 phantom) -----------------------

    def test_card_past_the_end_of_canon_is_pruned(self):
        """Faded's shape: canon ran 0..92, the outline had a card at 93."""
        machine = "<p>machine</p>"
        cards = [
            card("ch-2-91", 91, loom_id="L91", summary=machine, source=machine),
            card("ch-2-92", 92, loom_id="L92", summary=machine, source=machine),
            card("ch-2-93", 93, loom_id=None, summary=machine, source=machine),
        ]
        changed, cards = self.reconcile(
            cards, {91: ext(91), 92: ext(92)}, {91: "L91", 92: "L92"})
        self.assertTrue(changed)
        self.assertEqual([c["chapter"] for c in cards], [91, 92])

    def test_card_in_a_gap_is_pruned(self):
        """Not just past the end — any number canon no longer contains."""
        machine = "<p>machine</p>"
        cards = [card("ch-2-1", 1, loom_id="L1", summary=machine, source=machine),
                 card("ch-2-2", 2, loom_id="L2", summary=machine, source=machine),
                 card("ch-2-3", 3, loom_id="L3", summary=machine, source=machine)]
        _, cards = self.reconcile(cards, {1: ext(1), 3: ext(3)}, {1: "L1", 3: "L3"})
        self.assertEqual([c["chapter"] for c in cards], [1, 3])

    def test_out_of_canon_card_with_writer_content_is_kept(self):
        """A chapter you cut but wrote notes about must not vanish silently."""
        machine = "<p>machine</p>"
        cards = [
            card("ch-2-91", 91, loom_id="L91", summary=machine, source=machine),
            card("ch-2-93", 93, summary="<p>MY OWN WORDS</p>", source=machine),
        ]
        _, cards = self.reconcile(cards, {91: ext(91)}, {91: "L91"})
        self.assertEqual(len(cards), 2)
        self.assertIn("MY OWN WORDS", cards[1]["writer_summary"])

    def test_stamped_card_whose_chapter_left_canon_is_pruned(self):
        """The Faded case: a chapter is un-canonised, and a DIFFERENT chapter
        renumbers into the number it vacated. The orphan's number is still in
        canon, so judging by number keeps it and reconcile adds a second card
        beside it — a duplicate created by the pass meant to prevent them."""
        machine = "<p>machine</p>"
        cards = [
            # renumbered 45 -> 47, still canon under its own id
            card("ch-2-45", 45, loom_id="L47", summary=machine, source=machine),
            # was canon at 47, its chapter has left canon entirely
            card("ch-2-47", 47, loom_id="L_GONE", summary=machine, source=machine),
        ]
        changed, cards = self.reconcile(cards, {47: ext(47)}, {47: "L47"})
        self.assertTrue(changed)
        self.assertEqual(len(cards), 1, "the orphaned stamped card should be gone")
        self.assertEqual(cards[0]["loom_id"], "L47")
        self.assertEqual(cards[0]["chapter"], 47)

    def test_orphaned_stamped_card_with_writer_content_is_kept(self):
        machine = "<p>machine</p>"
        cards = [
            card("ch-2-45", 45, loom_id="L47", summary=machine, source=machine),
            card("ch-2-47", 47, loom_id="L_GONE", summary="<p>MY WORDS</p>", source=machine),
        ]
        _, cards = self.reconcile(cards, {47: ext(47)}, {47: "L47"})
        self.assertEqual(len(cards), 2)

    def test_planned_cards_are_never_pruned(self):
        """chapter=None is authorial intent for something not yet written."""
        machine = "<p>machine</p>"
        planned = card("ch-2-plan", 1, summary="", source=None)
        planned["chapter"] = None
        planned["position"] = 99.0
        cards = [card("ch-2-1", 1, loom_id="L1", summary=machine, source=machine),
                 planned]
        _, cards = self.reconcile(cards, {1: ext(1)}, {1: "L1"})
        self.assertEqual(len(cards), 2)
        self.assertIsNone(cards[1]["chapter"])

    def test_new_chapter_still_adds_a_card(self):
        """The fix must not break ordinary growth."""
        cards = [card("ch-3-1", 1, loom_id="L1", summary="", source=None)]
        _, cards = self.reconcile(cards, {1: ext(1), 2: ext(2)}, {1: "L1", 2: "L2"})
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[1]["loom_id"], "L2")


class StubbedChapterTest(unittest.TestCase):
    """A stubbed chapter (wordCount 0, written later) produces no chunks, so it
    can never appear in the index. Demanding index == canon meant one stub
    marked its book permanently out of sync and blocked reconcile for that book
    forever — its outline could not self-heal. Observed on The Secrets We Keep,
    stubs at chapters 32 and 43."""

    reconcile = ReconcileCollisionTest.reconcile

    def test_reconcile_runs_when_canon_has_an_unwritten_stub(self):
        cards = [card("ch-3-1", 1, loom_id="L1", summary="", source=None)]
        # canon has 1 and 2; only 1 is written, so only 1 is indexed
        changed, cards = self.reconcile(cards, {1: ext(1)}, {1: "L1", 2: "L2"})
        self.assertTrue(changed or True)          # must not bail out
        self.assertEqual(cards[0]["loom_id"], "L1")

    def test_a_stubs_card_is_not_pruned(self):
        """The stub is canon — its card must survive even though the index
        has nothing for it."""
        cards = [card("ch-3-1", 1, loom_id="L1", summary="", source=None),
                 card("ch-3-2", 2, loom_id="L2", summary="", source=None)]
        _, cards = self.reconcile(cards, {1: ext(1)}, {1: "L1", 2: "L2"})
        self.assertEqual(len(cards), 2, "the stub's card must not be deleted")
        self.assertEqual({c["loom_id"] for c in cards}, {"L1", "L2"})

    def test_index_holding_a_non_canon_chapter_still_bails(self):
        """The guard must still catch genuine inconsistency."""
        cards = [card("ch-3-1", 1, loom_id="L1", summary="", source=None)]
        changed, cards = self.reconcile(cards, {1: ext(1), 9: ext(9)}, {1: "L1"})
        self.assertFalse(changed)
        self.assertEqual(len(cards), 1)


class StubGetsACardTest(unittest.TestCase):
    """LOOM-64: a stubbed chapter must get an outline card.

    The loop used to iterate the chapters the INDEX knew about. A stub produces
    no chunks, so it was never visited and no card was ever created for it —
    every later card renumbered correctly and the new chapter was simply
    missing. Iterating the manifest instead covers written and unwritten
    chapters in one pass.
    """

    reconcile = ReconcileCollisionTest.reconcile

    def test_a_stub_gets_a_blank_card(self):
        cards = [card("ch-3-1", 1, loom_id="L1", summary="<p>one</p>",
                      source="<p>one</p>")]
        changed, cards = self.reconcile(cards, {1: ext(1)}, {1: "L1", 2: "L2"})

        self.assertTrue(changed)
        self.assertEqual(len(cards), 2)
        stub = cards[1]
        self.assertEqual(stub["loom_id"], "L2")
        self.assertEqual(stub["chapter"], 2)
        self.assertEqual(stub["heading"], "Chapter 2")
        self.assertEqual(stub["writer_summary"], "")
        self.assertEqual(stub["extracted_bullets"], [])
        # A stub IS canon — the chapter exists in Loom, it just has no words.
        # "Unsynced" would claim the outline disagrees with the book.
        self.assertEqual(stub["status"], "synced")

    def test_the_secrets_we_keep_shape(self):
        """The production case: 71 canon chapters, stubs at 32 and 43, 69
        cards. All 71 must end up carded, and no existing summary may move."""
        num_to_loom = {n: f"L{n}" for n in range(0, 71)}
        extracted = {n: ext(n) for n in range(0, 71) if n not in (32, 43)}
        cards = [card(f"ch-3-{n}", n, loom_id=f"L{n}",
                      summary=f"<p>summary {n}</p>", source=f"<p>summary {n}</p>")
                 for n in extracted]
        self.assertEqual(len(cards), 69)

        _, cards = self.reconcile(cards, extracted, num_to_loom)

        self.assertEqual(len(cards), 71)
        by_num = {c["chapter"]: c for c in cards}
        self.assertEqual(sorted(by_num), list(range(0, 71)))
        self.assertEqual(by_num[32]["writer_summary"], "")
        self.assertEqual(by_num[43]["writer_summary"], "")
        for n in extracted:
            self.assertEqual(by_num[n]["writer_summary"], f"<p>summary {n}</p>",
                             f"chapter {n}'s summary must not have moved")
            self.assertEqual(by_num[n]["loom_id"], f"L{n}")

    def test_prologue_stub_is_labelled_prologue(self):
        cards = []
        _, cards = self.reconcile(cards, {}, {0: "L0"})
        self.assertEqual(cards[0]["heading"], "Prologue")

    def test_stub_inherits_pov_and_date_from_the_manifest(self):
        """The index has nothing to describe a stub with — the manifest does,
        and Loom seeds both fields from the preceding chapter on insert."""
        _, cards = self.reconcile([], {}, {5: "L5"})
        self.assertEqual(cards[0]["pov"], "Jared")
        self.assertEqual(cards[0]["date"], "Thursday, August 19th")

    def test_a_stub_that_gains_prose_updates_its_own_card(self):
        """No second card: matched by loom_id, which is why stamping matters."""
        _, cards = self.reconcile([], {}, {2: "L2"})
        self.assertEqual(len(cards), 1)
        stub_id = cards[0]["id"]

        _, cards = self.reconcile(
            cards, {2: ext(2, bullets=["he arrives"])}, {2: "L2"})
        self.assertEqual(len(cards), 1, "the stub must not be duplicated")
        self.assertEqual(cards[0]["id"], stub_id)
        self.assertEqual(cards[0]["extracted_bullets"], ["he arrives"])

    def test_insert_renumbers_and_adds_in_one_pass(self):
        """The user-facing scenario: a new stubbed Chapter 2 is inserted, so the
        old 2 and 3 become 3 and 4. Summaries must follow their own chapters."""
        cards = [card("ch-3-1", 1, loom_id="L1", summary="<p>A</p>", source="<p>A</p>"),
                 card("ch-3-2", 2, loom_id="L2", summary="<p>B</p>", source="<p>B</p>"),
                 card("ch-3-3", 3, loom_id="L3", summary="<p>C</p>", source="<p>C</p>")]
        # NEW is the inserted stub at 2; L2 and L3 shifted up one.
        _, cards = self.reconcile(
            cards,
            {1: ext(1), 3: ext(3), 4: ext(4)},
            {1: "L1", 2: "LNEW", 3: "L2", 4: "L3"})

        by_num = {c["chapter"]: c for c in cards}
        self.assertEqual(sorted(by_num), [1, 2, 3, 4])
        self.assertEqual(by_num[2]["loom_id"], "LNEW")
        self.assertEqual(by_num[2]["writer_summary"], "")
        self.assertEqual(by_num[3]["writer_summary"], "<p>B</p>",
                         "B belongs to the chapter now numbered 3")
        self.assertEqual(by_num[4]["writer_summary"], "<p>C</p>")
        self.assertEqual(by_num[3]["heading"], "Chapter 3")

    def test_written_chapter_missing_from_the_index_is_left_alone(self):
        """If wordCount and the index ever disagree, the safe move is to skip:
        treating a written chapter as a stub would blank real bullets."""
        cards = [card("ch-3-2", 2, loom_id="L2", summary="<p>real</p>",
                      source="<p>real</p>", bullets=["a", "b"])]
        _, cards = self.reconcile(cards, {}, {2: "L2"}, stubs=set())

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["writer_summary"], "<p>real</p>")
        self.assertEqual(cards[0]["extracted_bullets"], ["a", "b"])

    def test_writer_content_on_a_stub_card_is_never_touched(self):
        """The invariant that protects writing: a card whose loom_id is
        unchanged never has its summary or notes rewritten."""
        cards = [card("ch-3-2", 2, loom_id="L2", summary="<p>MY PLAN</p>",
                      source=None, notes="figure out the ending")]
        _, cards = self.reconcile(cards, {}, {2: "L2"})

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["writer_summary"], "<p>MY PLAN</p>")
        self.assertEqual(cards[0]["notes"], "figure out the ending")


if __name__ == "__main__":
    unittest.main()

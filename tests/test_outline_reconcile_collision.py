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


class ReconcileCollisionTest(unittest.TestCase):
    def reconcile(self, cards, extracted, num_to_loom):
        with mock.patch.object(plan, "_extracted_chapters", return_value=extracted):
            changed = plan._auto_reconcile(3, cards, True, num_to_loom)
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

    def test_new_chapter_still_adds_a_card(self):
        """The fix must not break ordinary growth."""
        cards = [card("ch-3-1", 1, loom_id="L1", summary="", source=None)]
        _, cards = self.reconcile(cards, {1: ext(1), 2: ext(2)}, {1: "L1", 2: "L2"})
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[1]["loom_id"], "L2")


if __name__ == "__main__":
    unittest.main()

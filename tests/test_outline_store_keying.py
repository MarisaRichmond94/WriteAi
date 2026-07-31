"""Outline store keying and lazy migration (KAN-24).

`writer_data/plan_outline.json` was keyed by BOOK NUMBER. Book number is
positional: insert or reorder a book in Loom and every outline shifts, silently
attaching 300+ writer-facing cards to the wrong books. The store is now keyed on
Loom's cuid, which survives both.

Migration is lazy — numeric keys move to cuids on load, when resolvable — so
there is no big-bang rewrite of writer data.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_outline_store_keying -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import outline_store  # noqa: E402

CUID2 = "cmp8wtcs3000tzufxcrda4qg2"
CUID3 = "cmp8wtcs4000uzufx81vk506u"


class KeyingTest(unittest.TestCase):
    def test_key_is_the_cuid_when_resolvable(self):
        with mock.patch.object(outline_store, "loom_book_id_for", return_value=CUID2), \
             mock.patch.object(outline_store, "get_state"):
            self.assertEqual(outline_store.outline_key(2), CUID2)

    def test_key_falls_back_to_the_number(self):
        """A book with no readable manifest must still load and save."""
        with mock.patch.object(outline_store, "loom_book_id_for", return_value=None), \
             mock.patch.object(outline_store, "get_state"):
            self.assertEqual(outline_store.outline_key(2), "2")

    def test_key_survives_resolution_raising(self):
        with mock.patch.object(outline_store, "loom_book_id_for", side_effect=OSError), \
             mock.patch.object(outline_store, "get_state"):
            self.assertEqual(outline_store.outline_key(7), "7")


class MigrationTest(unittest.TestCase):
    def run_load(self, store, resolver):
        saved = {}
        with mock.patch.object(outline_store.writer_store, "plan_outline",
                               return_value=store), \
             mock.patch.object(outline_store.writer_store, "save_plan_outline",
                               side_effect=lambda v: saved.update(value=v)), \
             mock.patch.object(outline_store, "loom_book_id_for",
                               side_effect=lambda cfg, n: resolver.get(n)), \
             mock.patch.object(outline_store, "get_state"):
            out = outline_store.load_outlines()
        return out, saved.get("value")

    def test_numeric_keys_migrate_to_cuids(self):
        store = {"2": [{"id": "a"}], "3": [{"id": "b"}]}
        out, saved = self.run_load(store, {2: CUID2, 3: CUID3})
        self.assertEqual(set(out), {CUID2, CUID3})
        self.assertEqual(out[CUID2], [{"id": "a"}])
        self.assertIsNotNone(saved, "a migration must persist")

    def test_card_contents_are_never_altered(self):
        cards = [{"id": "a", "writer_summary": "<p>mine</p>"}]
        out, _ = self.run_load({"2": cards}, {2: CUID2})
        self.assertEqual(out[CUID2], cards)

    def test_already_migrated_store_is_not_rewritten(self):
        out, saved = self.run_load({CUID2: [{"id": "a"}]}, {2: CUID2})
        self.assertEqual(set(out), {CUID2})
        self.assertIsNone(saved, "an already-migrated store should be a pure read")

    def test_unresolvable_book_keeps_its_number_and_is_retried(self):
        out, saved = self.run_load({"9": [{"id": "a"}]}, {})
        self.assertEqual(set(out), {"9"}, "must not be dropped")
        self.assertIsNone(saved)

    def test_partial_migration_moves_only_what_resolves(self):
        store = {"2": [{"id": "a"}], "9": [{"id": "b"}]}
        out, _ = self.run_load(store, {2: CUID2})
        self.assertEqual(set(out), {CUID2, "9"})

    def test_both_shapes_present_is_left_alone(self):
        """One of them holds cards the writer can see. Guessing which risks
        discarding writing, so leave both and report it."""
        store = {"2": [{"id": "legacy"}], CUID2: [{"id": "new"}]}
        out, saved = self.run_load(store, {2: CUID2})
        self.assertEqual(set(out), {"2", CUID2}, "neither may be dropped")
        self.assertEqual(out[CUID2], [{"id": "new"}])
        self.assertEqual(out["2"], [{"id": "legacy"}])
        self.assertIsNone(saved)


if __name__ == "__main__":
    unittest.main()

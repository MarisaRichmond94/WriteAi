"""Tests for stable-id Chroma collection naming and migration (KAN-10).

The collection used to be named `slugify(SERIES_NAME)`, making the whole vector
index addressable by a display string. Changing SERIES_NAME meant
get_or_create_collection quietly created a NEW, EMPTY collection: every query
returned nothing while the real index sat untouched under the old name. Silent,
and indistinguishable from catastrophic loss.

Migration is a RENAME (Chroma's modify(name=...)), never a rebuild —
re-embedding would cost real API spend for no benefit.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_stable_collection_name -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage import SeriesStore, slugify, stable_collection_name  # noqa: E402

CUID = "cmp8wtcr50000zufxy70xic4e"


class FakeCollection:
    def __init__(self, name, registry):
        self.name = name
        self._registry = registry
        self.configuration_json = {"hnsw": {"ef_search": 2000}}

    def modify(self, name=None, metadata=None, configuration=None):
        if name:
            self._registry[name] = self._registry.pop(self.name)
            self.name = name


class FakeChroma:
    """Minimal stand-in: a name -> collection registry that records renames."""

    def __init__(self, initial=()):
        self.registry = {}
        for n in initial:
            self.registry[n] = FakeCollection(n, self.registry)
        self.created = []

    def list_collections(self):
        return list(self.registry.values())

    def get_collection(self, name):
        return self.registry[name]

    def get_or_create_collection(self, name, metadata=None):
        if name not in self.registry:
            self.registry[name] = FakeCollection(name, self.registry)
            self.created.append(name)
        return self.registry[name]


class NameTest(unittest.TestCase):
    def test_stable_name_is_derived_from_the_cuid(self):
        self.assertEqual(stable_collection_name(CUID), f"series-{CUID}")

    def test_stable_name_satisfies_chroma_constraints(self):
        n = stable_collection_name(CUID)
        self.assertTrue(3 <= len(n) <= 63)
        self.assertRegex(n, r"^[a-z0-9][a-z0-9._-]*$")

    def test_renaming_the_series_does_not_change_the_stable_name(self):
        """The entire point: display name moves, identity does not."""
        self.assertEqual(stable_collection_name(CUID), stable_collection_name(CUID))
        self.assertNotEqual(slugify("The Dark Horse Series"),
                            slugify("The Dark Horse Saga"))


class MigrationTest(unittest.TestCase):
    """Exercises _migrate_legacy_collections through a real SeriesStore."""

    def build(self, existing, loom_series_id, series_name="The Dark Horse Series"):
        fake = FakeChroma(existing)
        store = SeriesStore.__new__(SeriesStore)          # skip __init__
        store._chroma = fake
        store._legacy_collection_name = slugify(series_name)
        store._collection_name = (stable_collection_name(loom_series_id)
                                  if loom_series_id else store._legacy_collection_name)
        store._migrate_legacy_collections()
        return store, fake

    def test_legacy_collection_is_renamed_not_rebuilt(self):
        legacy = slugify("The Dark Horse Series")
        store, fake = self.build([legacy, f"{legacy[:57]}-notes"], CUID)
        self.assertIn(f"series-{CUID}", fake.registry)
        self.assertIn(f"series-{CUID}"[:57] + "-notes", fake.registry)
        self.assertNotIn(legacy, fake.registry)
        self.assertEqual(fake.created, [], "must rename, never create")

    def test_notes_collection_migrates_too(self):
        legacy = slugify("The Dark Horse Series")
        _, fake = self.build([legacy, f"{legacy[:57]}-notes"], CUID)
        self.assertTrue(any(n.endswith("-notes") and CUID in n for n in fake.registry))

    def test_no_stable_id_leaves_everything_alone(self):
        legacy = slugify("The Dark Horse Series")
        store, fake = self.build([legacy], None)
        self.assertEqual(store._collection_name, legacy)
        self.assertIn(legacy, fake.registry)
        self.assertEqual(fake.created, [])

    def test_already_migrated_is_a_no_op(self):
        _, fake = self.build([f"series-{CUID}"], CUID)
        self.assertIn(f"series-{CUID}", fake.registry)
        self.assertEqual(fake.created, [])

    def test_fresh_store_with_nothing_to_migrate(self):
        _, fake = self.build([], CUID)
        self.assertEqual(fake.registry, {}, "migration alone must not create")

    def test_target_already_present_does_not_clobber_it(self):
        """If both names exist, the stable one wins and the legacy is left be —
        silently overwriting a populated target would destroy an index."""
        legacy = slugify("The Dark Horse Series")
        _, fake = self.build([legacy, f"series-{CUID}"], CUID)
        self.assertIn(f"series-{CUID}", fake.registry)
        self.assertIn(legacy, fake.registry)

    def test_rename_failure_is_survivable(self):
        legacy = slugify("The Dark Horse Series")
        fake = FakeChroma([legacy])
        with mock.patch.object(FakeCollection, "modify",
                               side_effect=RuntimeError("chroma is unhappy")):
            store = SeriesStore.__new__(SeriesStore)
            store._chroma = fake
            store._legacy_collection_name = legacy
            store._collection_name = stable_collection_name(CUID)
            store._migrate_legacy_collections()   # must not raise
        self.assertIn(legacy, fake.registry, "the old index must still be there")


if __name__ == "__main__":
    unittest.main()

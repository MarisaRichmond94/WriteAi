"""Unit tests for src/canonical.py — character-name canonicalization.

Covers the v1 heuristics (first-token-anchored merging) and the flag-gated
ENABLE_CANON_V2 behavior: title-stripped matching, unique-surname attach,
normalized user-map lookup, and alias dedup.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_canonical -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.canonical import Canonicalizer, flatten_user_map


def make_db(prose: str, names: list[str], pov: str | None = None):
    """One-chunk fixture: every name in `names` was tagged on that chunk."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE chunks (chunk_id TEXT, book_number INT, "
               "chapter_number INT, text TEXT, pov_character TEXT)")
    db.execute("CREATE TABLE characters (chunk_id TEXT, name TEXT)")
    db.execute("INSERT INTO chunks VALUES ('c1', 1, 1, ?, ?)", (prose, pov))
    for n in names:
        db.execute("INSERT INTO characters VALUES ('c1', ?)", (n,))
    return db


def build(db, cmap=None, v2=False):
    os.environ["ENABLE_CANON_V2"] = "true" if v2 else "false"
    try:
        canon = Canonicalizer(db)
        canon._build(cmap or {"map": {}, "hidden": []})
        return canon
    finally:
        del os.environ["ENABLE_CANON_V2"]


PRICHARD_PROSE = ("Special Agent Jesse Prichard flashed his badge. "
                  "Agent Prichard nodded once. Prichard left at dawn.")
PRICHARD_TAGS = ["Jesse Prichard", "Agent Prichard",
                 "Special Agent Jesse Prichard", "Prichard",
                 "Agents Prichard"]  # last one is ungrounded (not in prose)


class TestV1Unchanged(unittest.TestCase):
    def test_title_variants_stay_separate(self):
        canon = build(make_db(PRICHARD_PROSE, PRICHARD_TAGS), v2=False)
        self.assertIn("Jesse Prichard", canon.entities)
        self.assertIn("Agent Prichard", canon.entities)
        self.assertIn("Prichard", canon.entities)
        # ungrounded "Agents Prichard" folds into "Agent Prichard" (pass 3
        # strips the plural s), leaving four separate Prichard entities
        self.assertEqual(canon.variant_to_entity["Agents Prichard"],
                         "Agent Prichard")
        self.assertEqual(len(canon.entities), 4)

    def test_first_token_subsequence_merge(self):
        prose = "Chase Gatlin and Chase Ryder Gatlin are one boy."
        canon = build(make_db(prose, ["Chase Gatlin", "Chase Ryder Gatlin"]),
                      v2=False)
        self.assertEqual(len(canon.entities), 1)
        (e,) = canon.entities.values()
        self.assertEqual(sorted([e.name] + e.aliases),
                         ["Chase Gatlin", "Chase Ryder Gatlin"])


class TestV2TitleFold(unittest.TestCase):
    def test_all_prichard_variants_fold(self):
        canon = build(make_db(PRICHARD_PROSE, PRICHARD_TAGS), v2=True)
        self.assertEqual(list(canon.entities), ["Jesse Prichard"])
        e = canon.entities["Jesse Prichard"]
        self.assertEqual(sorted(e.aliases),
                         ["Agent Prichard", "Prichard",
                          "Special Agent Jesse Prichard"])
        self.assertEqual(canon.quarantined, [])
        # every raw variant resolves to the canonical entity
        for tag in PRICHARD_TAGS:
            self.assertEqual(canon.variant_to_entity[tag], "Jesse Prichard")

    def test_ambiguous_surname_stays_separate(self):
        prose = "Chase Gatlin met Noah Gatlin. Gatlin said nothing."
        canon = build(make_db(prose, ["Chase Gatlin", "Noah Gatlin", "Gatlin"]),
                      v2=True)
        self.assertIn("Gatlin", canon.entities)  # two candidates -> no attach

    def test_title_forms_without_real_head_do_not_cycle(self):
        prose = "Agent Prichard met Special Agent Prichard."
        canon = build(make_db(prose, ["Agent Prichard",
                                      "Special Agent Prichard"]), v2=True)
        # no real-name head to fold into: both survive, no infinite loop
        self.assertEqual(len(canon.entities), 2)


class TestV2MapLookup(unittest.TestCase):
    def test_normalized_map_lookup(self):
        cmap = {"map": {"Agent Prichard": "Jesse Prichard"}, "hidden": []}
        prose = "Jesse Prichard waited. agent prichard, they said."
        db = make_db(prose, ["Jesse Prichard", "agent prichard,"])
        self.assertIn("agent prichard,", build(db, cmap, v2=False).entities)
        canon = build(db, cmap, v2=True)
        self.assertEqual(list(canon.entities), ["Jesse Prichard"])

    def test_no_duplicate_looking_alias_pills(self):
        cmap = {"map": {"Prichard": "Jesse Prichard",
                        "prichard.": "Jesse Prichard"}, "hidden": []}
        prose = "Jesse Prichard waited. Prichard left."
        canon = build(make_db(prose, ["Jesse Prichard", "Prichard"]),
                      cmap, v2=True)
        e = canon.entities["Jesse Prichard"]
        self.assertEqual(e.aliases, ["Prichard"])


class TestFlattenUserMap(unittest.TestCase):
    def test_chains_and_self_maps_collapse(self):
        m = {"Agent Prichard": "Prichard",
             "Prichard": "Jesse Prichard",
             "Jesse Prichard": "Jesse Prichard"}
        self.assertEqual(flatten_user_map(m),
                         {"Agent Prichard": "Jesse Prichard",
                          "Prichard": "Jesse Prichard"})

    def test_cycle_does_not_hang(self):
        m = {"A": "B", "B": "A"}
        out = flatten_user_map(m)
        self.assertEqual(len(out), 2)  # resolved deterministically, no hang


if __name__ == "__main__":
    unittest.main()

"""The Explore chat's filters must do what the UI says they do (LOOM-113).

Two silent behaviours lived in `chat_stream`, both invisible from the outside:

1. A POV filter that matched nothing was DISCARDED, and the answer was built
   from the unfiltered excerpts while the filter bar still showed it active.
   In a story told in limited POV, answering about Noah out of Jared's
   chapters is worse than reporting there was nothing to find.

2. A book filter became a contiguous `Scope(book_min, book_max)` RANGE, and
   the exact set was applied afterwards as a post-filter. Selecting books 1
   and 4 therefore retrieved across 1-4 and discarded 2 and 3 — retrieval
   budget spent on excluded books, and a thinner slice of the books actually
   chosen than the caller believed.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_chat_filters -v
"""

from __future__ import annotations

import unittest

from src.query_router import Scope
from src.retriever import _scope_chroma, _scope_sql


class ExactBookSetReachesTheQuery(unittest.TestCase):
    """The set must constrain retrieval itself, not a post-filter."""

    def test_sql_emits_in_clause_for_a_set(self):
        where, params = _scope_sql(Scope(books=frozenset({1, 4})))
        self.assertIn("c.book_number IN (?,?)", where)
        self.assertEqual(params[:2], [1, 4])

    def test_sql_params_are_sorted_for_a_stable_statement(self):
        a, _ = _scope_sql(Scope(books=frozenset({4, 1})))
        b, _ = _scope_sql(Scope(books=frozenset({1, 4})))
        self.assertEqual(a, b, "same set must produce the same SQL text")

    def test_chroma_emits_in_filter_for_a_set(self):
        where = _scope_chroma(Scope(books=frozenset({1, 4})))
        self.assertEqual(where, {"book_number": {"$in": [1, 4]}})

    def test_set_and_range_both_constrain(self):
        """chat.py sets both: the range so `describe()` and the temporal logic
        keep the span they reason about, the set so exclusion is real."""
        scope = Scope(book_min=1, book_max=4, books=frozenset({1, 4}))
        where, params = _scope_sql(scope)
        self.assertIn("IN (?,?)", where)
        self.assertIn("c.book_number >= ?", where)
        self.assertIn("c.book_number <= ?", where)
        self.assertEqual(params, [1, 4, 1, 4])

        chroma = _scope_chroma(scope)
        self.assertIn("$and", chroma)
        self.assertIn({"book_number": {"$in": [1, 4]}}, chroma["$and"])

    def test_no_set_is_unchanged(self):
        """The flag-off path: a plain range must produce exactly what it did
        before, or every non-Explore caller changes behaviour."""
        where, params = _scope_sql(Scope(book_min=2, book_max=3))
        self.assertEqual(where, "c.book_number >= ? AND c.book_number <= ?")
        self.assertEqual(params, [2, 3])
        self.assertIsNone(_scope_chroma(Scope()))


class ScopeDescribesItselfHonestly(unittest.TestCase):
    """`describe()` goes into the prompt — it must not claim a span the query
    does not actually cover."""

    def test_noncontiguous_set_is_listed_not_ranged(self):
        self.assertEqual(Scope(books=frozenset({1, 4})).describe(), "books 1, 4")

    def test_contiguous_set_reads_as_a_range(self):
        self.assertEqual(Scope(books=frozenset({1, 2, 3})).describe(), "books 1-3")

    def test_single_book(self):
        self.assertEqual(Scope(books=frozenset({3})).describe(), "book 3")

    def test_set_wins_over_the_range_it_accompanies(self):
        """chat.py passes both; the set is the truthful one."""
        scope = Scope(book_min=1, book_max=4, books=frozenset({1, 4}))
        self.assertEqual(scope.describe(), "books 1, 4")

    def test_unscoped_is_unchanged(self):
        self.assertEqual(Scope().describe(), "the whole series")


class StarvedPovFilterIsReported(unittest.TestCase):
    """The POV filter stays a post-filter (POV is a property of the retrieved
    chunk), but an empty result is now reported rather than discarded."""

    @staticmethod
    def _apply(excerpts, pov_filter):
        """The exact shape chat.py now uses."""
        if not pov_filter:
            return excerpts, False
        povs = set(pov_filter)
        kept = [e for e in excerpts if e.get("pov_character") in povs]
        return kept, not kept

    def test_matching_povs_are_kept(self):
        excerpts = [{"pov_character": "Noah Gatlin"},
                    {"pov_character": "Jared Gatlin"}]
        kept, starved = self._apply(excerpts, ["Noah Gatlin"])
        self.assertEqual(kept, [{"pov_character": "Noah Gatlin"}])
        self.assertFalse(starved)

    def test_no_match_starves_rather_than_unfiltering(self):
        excerpts = [{"pov_character": "Jared Gatlin"},
                    {"pov_character": "Chase Gatlin"}]
        kept, starved = self._apply(excerpts, ["Emma Mendoza"])
        self.assertEqual(kept, [], "the old code returned the UNFILTERED set here")
        self.assertTrue(starved)

    def test_no_filter_is_a_passthrough(self):
        excerpts = [{"pov_character": "Jared Gatlin"}]
        kept, starved = self._apply(excerpts, [])
        self.assertEqual(kept, excerpts)
        self.assertFalse(starved)


class ChatPathStaysReadOnly(unittest.TestCase):
    """The chat endpoint answers from the index and must never write. Pinned at
    source level, the same way Loom pins its own read-only routes."""

    def test_chat_router_calls_no_store_writer(self):
        from config import REPO_ROOT
        source = (REPO_ROOT / "server" / "routers" / "chat.py").read_text("utf-8")
        for forbidden in ("writer_store.save", "save_plan_outline",
                          "save_writer_events", "save_writer_characters",
                          "save_character_map", "ingest_run"):
            self.assertNotIn(forbidden, source,
                             f"{forbidden} must not be reachable from chat.py "
                             "— answering a question cannot mutate the store")


if __name__ == "__main__":
    unittest.main()

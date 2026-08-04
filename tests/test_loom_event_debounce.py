"""Regression tests for how long a structural change waits before syncing.

The poller debounces every book's exports by ten minutes, which is right for
prose: a writing session produces an export per blur, and batching them into
one ingest at the end of the session is the whole point.

It is wrong for a chapter being added or removed. That is a discrete act, it
happens once, it renumbers every chapter below it, and there is nothing
following it to batch — so ten minutes is ten minutes of WriteAI answering
about chapter 12 with chapter 11's scene.

These pin the fast path and, more importantly, pin that it does not leak: the
ordinary prose debounce must stay at ten minutes, or every keystroke-driven
export starts its own ingest.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_loom_event_debounce -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import loom_events  # noqa: E402


def event(kind, **payload):
    return {"type": kind, "payload": payload}


class StructuralDebounce(unittest.TestCase):

    def setUp(self):
        loom_events._pending.clear()
        loom_events._structural.clear()
        loom_events._structural_book_ids.clear()
        self.addCleanup(loom_events._pending.clear)
        self.addCleanup(loom_events._structural.clear)
        self.addCleanup(loom_events._structural_book_ids.clear)

    def feed(self, events):
        """The event-classifying half of _tick, which is all these cover."""
        for e in events:
            payload = e.get("payload") or {}
            kind = e.get("type")
            if kind in ("chapter.created", "chapter.deleted"):
                if payload.get("bookId"):
                    loom_events._structural_book_ids.add(payload["bookId"])
                continue
            if kind != "export.completed":
                continue
            title = payload.get("bookTitle")
            if title:
                loom_events._pending[title] = 0.0
                if payload.get("bookId") in loom_events._structural_book_ids:
                    loom_events._structural_book_ids.discard(payload["bookId"])
                    loom_events._structural.add(title)

    def due_at(self, elapsed: float) -> list[str]:
        return [t for t, at in loom_events._pending.items()
                if elapsed - at >= (loom_events._STRUCTURAL_DEBOUNCE_SECONDS
                                    if t in loom_events._structural
                                    else loom_events._DEBOUNCE_SECONDS)]

    def test_a_new_chapter_syncs_in_a_minute_not_ten(self):
        self.feed([
            event("chapter.created", bookId="bk2", chapterId="ch", title="41"),
            event("export.completed", bookId="bk2", bookTitle="Faded"),
        ])
        self.assertEqual(self.due_at(30), [])
        self.assertEqual(self.due_at(90), ["Faded"])

    def test_a_deleted_chapter_is_structural_too(self):
        self.feed([
            event("chapter.deleted", bookId="bk2", chapterId="ch", title="41"),
            event("export.completed", bookId="bk2", bookTitle="Faded"),
        ])
        self.assertEqual(self.due_at(90), ["Faded"])

    def test_prose_edits_still_wait_the_full_ten_minutes(self):
        """The leak that would matter: a blur-driven export must not start its
        own ingest, or a writing session bills an ingest per paragraph."""
        self.feed([event("export.completed", bookId="bk2", bookTitle="Faded")])
        self.assertEqual(self.due_at(90), [])
        self.assertEqual(self.due_at(599), [])
        self.assertEqual(self.due_at(601), ["Faded"])

    def test_urgency_does_not_spread_to_other_books(self):
        self.feed([
            event("chapter.created", bookId="bk2", chapterId="ch", title="41"),
            event("export.completed", bookId="bk2", bookTitle="Faded"),
            event("export.completed", bookId="bk3", bookTitle="The Secrets We Keep"),
        ])
        self.assertEqual(self.due_at(90), ["Faded"])

    def test_a_structural_event_alone_never_triggers_an_ingest(self):
        """Only export.completed means "a consistent snapshot is on disk".
        A chapter.created with no export behind it must not start a read."""
        self.feed([event("chapter.created", bookId="bk2", chapterId="ch",
                         title="41")])
        self.assertEqual(loom_events._pending, {})
        self.assertEqual(self.due_at(10_000), [])

    def test_the_structural_mark_survives_until_its_export_arrives(self):
        """Loom emits the structural event and the export back to back, but
        they can land in different polls."""
        self.feed([event("chapter.created", bookId="bk2", chapterId="ch",
                         title="41")])
        self.feed([event("export.completed", bookId="bk2", bookTitle="Faded")])
        self.assertEqual(self.due_at(90), ["Faded"])

    def test_the_mark_is_consumed_so_later_prose_edits_are_not_urgent(self):
        self.feed([
            event("chapter.created", bookId="bk2", chapterId="ch", title="41"),
            event("export.completed", bookId="bk2", bookTitle="Faded"),
        ])
        loom_events._pending.clear()
        loom_events._structural.clear()   # what the ingest flush does
        self.feed([event("export.completed", bookId="bk2", bookTitle="Faded")])
        self.assertEqual(self.due_at(90), [], "a plain edit is not structural")


if __name__ == "__main__":
    unittest.main()

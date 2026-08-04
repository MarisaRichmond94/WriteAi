"""Regression tests for the cost of inserting a chapter mid-book.

The chunk id is positional (`b02.c040.s01.k00`), so inserting a chapter above
chapter 40 renumbers every chapter below it and hands the diff a book whose
entire tail looks brand new. Before `detect_moved_chunks`, that tail was priced
and extracted as new prose: inserting one chapter into Faded (94 chapters, 368
chunks) re-ran Haiku over ~215 chunks whose words had not changed at all.

These pin the two halves that make it cheap: the same prose under a new id is
recognised as a MOVE, and a move carries the donor's metadata instead of
calling the model.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_moved_chunks -v
"""

from __future__ import annotations

import unittest

from src.chunker import Chunk
from src.ingestion import (BookDiff, carry_chunks, chunk_text_hash,
                           detect_moved_chunks, diff_chunks)


def chunk(chapter: int, text: str, idx: int = 0, prefix: str = "") -> Chunk:
    return Chunk(
        text=text, context_prefix=prefix, book_number=2, book_title="Faded",
        chapter_number=chapter, chapter_kind="chapter", heading=f"Chapter {chapter}",
        scene_number=1, chunk_index=idx, total_chunks_in_scene=1,
        pov_character="Ellis", date_line=None, part_number=None, part_title=None,
        word_count=len(text.split()),
    )


class DetectMovedChunks(unittest.TestCase):

    def test_insert_renumbers_the_tail_as_moves_not_rewritten_prose(self):
        """The whole point: an insert must not price the tail as new work.

        Note what the raw diff calls it. An insert makes the book LONGER, so
        every old id still exists and holds its predecessor's prose — the
        tail is `updated`, nothing is `new` but the last chunk, and NOTHING
        is deleted. Detection keyed off deletions would find none of this.
        """
        before = [chunk(n, f"prose of chapter {n}") for n in (40, 41, 42)]
        index = {c.chunk_id: chunk_text_hash(c) for c in before}

        # A chapter is inserted at 40: the old 40/41/42 become 41/42/43 and a
        # genuinely new chapter 40 takes their place.
        after = [chunk(40, "brand new chapter")] + [
            chunk(n + 1, f"prose of chapter {n}") for n in (40, 41, 42)]

        d = diff_chunks(after, index, book_number=2)
        self.assertEqual(len(d.updated), 3, "by id, the tail looks rewritten")
        self.assertEqual(len(d.new), 1)
        self.assertEqual(d.deleted_ids, [], "an insert deletes nothing")

        detect_moved_chunks(d, index, book_number=2)

        self.assertEqual([c.text for c in d.updated + d.new],
                         ["brand new chapter"])
        self.assertEqual(len(d.moved), 3)
        # Each mover is paired with the donor holding the identical prose.
        self.assertEqual(
            {c.chunk_id: donor for c, donor in d.moved},
            {"b02.c041.s01.k00": "b02.c040.s01.k00",
             "b02.c042.s01.k00": "b02.c041.s01.k00",
             "b02.c043.s01.k00": "b02.c042.s01.k00"},
        )

    def test_deleting_a_chapter_shifts_the_tail_up_as_moves(self):
        """The mirror case: a removed chapter shortens the book, so the tail
        moves UP and the trailing ids fall off as deletions."""
        before = [chunk(n, f"prose of chapter {n}") for n in (40, 41, 42)]
        index = {c.chunk_id: chunk_text_hash(c) for c in before}
        after = [chunk(40, "prose of chapter 41"), chunk(41, "prose of chapter 42")]

        d = diff_chunks(after, index, book_number=2)
        detect_moved_chunks(d, index, book_number=2)

        self.assertEqual(len(d.moved), 2)
        self.assertEqual(d.new + d.updated, [])
        self.assertEqual(d.deleted_ids, ["b02.c042.s01.k00"])

    def test_edited_prose_is_never_treated_as_a_move(self):
        """A move is byte-identical prose. Anything else must reach the model."""
        before = [chunk(40, "the original words")]
        index = {c.chunk_id: chunk_text_hash(c) for c in before}
        after = [chunk(40, "the original words"), chunk(41, "the original words, revised")]

        d = diff_chunks(after, index, book_number=2)
        detect_moved_chunks(d, index, book_number=2)
        self.assertEqual(d.moved, [], "a revision is not a move")
        self.assertEqual([c.chapter_number for c in d.new], [41])

    def test_duplicate_prose_shares_one_donor(self):
        """Byte-identical chunks earn the same reading, so one donor serves
        every mover holding those words — no pool to exhaust."""
        before = [chunk(40, "unique words"), chunk(41, "same words")]
        index = {c.chunk_id: chunk_text_hash(c) for c in before}
        after = [chunk(40, "unique words"), chunk(41, "same words"),
                 chunk(42, "same words"), chunk(43, "same words")]

        d = diff_chunks(after, index, book_number=2)
        detect_moved_chunks(d, index, book_number=2)
        self.assertEqual(len(d.moved), 2, "c042 and c043; c041 was unchanged")
        self.assertEqual({donor for _, donor in d.moved}, {"b02.c041.s01.k00"})
        self.assertEqual(d.new + d.updated, [])

    def test_another_books_chunks_are_never_donors(self):
        """Donors are scoped to the book. Identical prose across two books is
        a coincidence, not a move, and must not cross-contaminate metadata."""
        other = Chunk(
            text="same words", context_prefix="", book_number=3,
            book_title="The Secrets We Keep", chapter_number=5,
            chapter_kind="chapter", heading="Chapter 5", scene_number=1,
            chunk_index=0, total_chunks_in_scene=1, pov_character=None,
            date_line=None, part_number=None, part_title=None, word_count=2)
        index = {other.chunk_id: chunk_text_hash(other)}

        d = diff_chunks([chunk(40, "same words")], index, book_number=2)
        detect_moved_chunks(d, index, book_number=2)
        self.assertEqual(d.moved, [])
        self.assertEqual(len(d.new), 1)

    def test_an_empty_index_has_nothing_to_move_from(self):
        """A first ingest, or --full, must extract everything."""
        d = BookDiff(new=[chunk(95, "a new final chapter")])
        detect_moved_chunks(d, {}, book_number=2)
        self.assertEqual(d.moved, [])
        self.assertEqual(len(d.new), 1)


class _FakeEmbedder:
    def __init__(self):
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        return [[0.0, 1.0] for _ in texts]


class _FakeStore:
    def __init__(self, metadata):
        self._metadata = metadata
        self.upserted = []

    def get_metadata(self, chunk_ids):
        return {cid: self._metadata[cid] for cid in chunk_ids
                if cid in self._metadata}

    def upsert_chunks(self, records):
        self.upserted.extend(records)


class _Cfg:
    enable_note_ranking = False


class CarryChunks(unittest.TestCase):

    def test_metadata_is_reused_and_the_new_position_wins(self):
        moved = [(chunk(41, "prose of chapter 40"), "b02.c040.s01.k00")]
        store = _FakeStore({"b02.c040.s01.k00": {"characters_present": ["Ellis"]}})
        embedder = _FakeEmbedder()

        res = carry_chunks(_Cfg(), moved, embedder, store)

        self.assertEqual(res["carried"], 1)
        self.assertEqual(res["refused"], [])
        record = store.upserted[0]
        # the donor's reading of the prose, carried verbatim...
        self.assertEqual(record["metadata"], {"characters_present": ["Ellis"]})
        # ...but every positional field comes from where the chunk now IS.
        self.assertEqual(record["chunk"].chapter_number, 41)
        self.assertEqual(record["chunk"].chunk_id, "b02.c041.s01.k00")
        self.assertEqual(record["text_hash"], chunk_text_hash(record["chunk"]))

    def test_embeddings_are_recomputed_not_reused(self):
        """context_prefix rides in embedding_text and changes at the seam, so
        the vector must be recomputed. It is a local model — this is free."""
        moved = [(chunk(41, "prose", prefix="a different preceding sentence."),
                  "b02.c040.s01.k00")]
        store = _FakeStore({"b02.c040.s01.k00": {}})
        embedder = _FakeEmbedder()

        carry_chunks(_Cfg(), moved, embedder, store)

        self.assertEqual(len(embedder.calls), 1)
        self.assertIn("a different preceding sentence.", embedder.calls[0][0])

    def test_a_donor_without_metadata_is_refused_not_carried(self):
        """A chunk whose extraction previously failed must not be laundered
        into a metadata-less chunk under a new id — it goes back through the
        normal path so the gap is filled rather than propagated."""
        good = chunk(41, "extracted prose")
        bad = chunk(42, "never extracted")
        store = _FakeStore({"b02.c040.s01.k00": {"characters_present": []}})
        moved = [(good, "b02.c040.s01.k00"), (bad, "b02.c041.s01.k00")]

        res = carry_chunks(_Cfg(), moved, _FakeEmbedder(), store)

        self.assertEqual(res["carried"], 1)
        self.assertEqual(res["refused"], [bad])
        self.assertEqual(len(store.upserted), 1)

    def test_nothing_moved_touches_neither_store_nor_embedder(self):
        store = _FakeStore({})
        embedder = _FakeEmbedder()
        res = carry_chunks(_Cfg(), [], embedder, store)
        self.assertEqual(res, {"carried": 0, "refused": []})
        self.assertEqual(store.upserted, [])
        self.assertEqual(embedder.calls, [])


if __name__ == "__main__":
    unittest.main()

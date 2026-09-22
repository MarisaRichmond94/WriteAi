"""Enrichment-gap detection for the review pane: synced chapters with no
enrichment rows are invisible to the story-so-far notes, so the review
flags them to both the model (a notes line) and the author (a notice)."""

import sqlite3

from server.routers.review import _enrichment_gaps, _gap_labels


def _db(*, tables: bool = True) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE chunks (book_number INT, chapter_number INT)")
    if tables:
        db.execute("CREATE TABLE events (book_number INT, chapter_number INT)")
        db.execute("CREATE TABLE chapter_summaries "
                   "(book_number INT, chapter_number INT)")
    return db


def _sync(db, book, chapters):
    db.executemany("INSERT INTO chunks VALUES (?, ?)",
                   [(book, c) for c in chapters])


def test_fully_enriched_book_has_no_gaps():
    db = _db()
    _sync(db, 1, [1, 2, 3])
    db.executemany("INSERT INTO chapter_summaries VALUES (?, ?)",
                   [(1, 1), (1, 2), (1, 3)])
    assert _enrichment_gaps(db, 1, 4) == []


def test_unsummarized_recent_chapters_are_gaps():
    db = _db()
    _sync(db, 1, [1, 2, 3, 4])
    db.execute("INSERT INTO chapter_summaries VALUES (1, 1)")
    db.execute("INSERT INTO events VALUES (1, 2)")   # events alone cover ch 2
    assert _enrichment_gaps(db, 1, 5) == [(1, 3), (1, 4)]


def test_scope_excludes_the_reviewed_chapter_and_later():
    db = _db()
    _sync(db, 1, [1, 2, 3])
    # nothing enriched, but only chapters BEFORE the reviewed one count
    assert _enrichment_gaps(db, 1, 2) == [(1, 1)]


def test_pasted_draft_scope_covers_the_whole_book():
    db = _db()
    _sync(db, 1, [1, 2])
    assert _enrichment_gaps(db, 1, None) == [(1, 1), (1, 2)]


def test_missing_enrichment_tables_mean_everything_is_a_gap():
    db = _db(tables=False)
    _sync(db, 1, [1, 2])
    assert _enrichment_gaps(db, 1, 3) == [(1, 1), (1, 2)]


def test_earlier_book_gaps_are_included():
    db = _db()
    _sync(db, 1, [1])
    _sync(db, 2, [1])
    db.execute("INSERT INTO chapter_summaries VALUES (2, 1)")
    assert _enrichment_gaps(db, 2, 2) == [(1, 1)]


def test_gap_labels_compress_runs_per_book():
    assert _gap_labels([(1, 3), (1, 4), (1, 5), (1, 7), (2, 1)]) == \
        ["Book 1 Ch 3-Ch 5", "Book 1 Ch 7", "Book 2 Ch 1"]


def test_gap_labels_name_the_prologue():
    assert _gap_labels([(1, 0), (1, 1)]) == ["Book 1 Prologue-Ch 1"]


def test_gap_labels_empty():
    assert _gap_labels([]) == []

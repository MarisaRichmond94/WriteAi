"""Review prompt budget: the pieces that keep per-review cost bounded —
story-so-far gisting (and, in later commits, the per-persona excerpt budget
and the system-block layout)."""

from server.routers.review import _gist


def test_gist_takes_first_sentence():
    assert _gist("Mara flees the citadel. She hides in the marsh. Dawn.") == \
        "Mara flees the citadel."


def test_gist_handles_other_terminators():
    assert _gist("Will she return? Nobody knows yet.") == "Will she return?"


def test_gist_spans_newlines():
    assert _gist("A hard\nchoice is made. Aftermath follows.") == \
        "A hard\nchoice is made."


def test_gist_returns_unterminated_text_whole():
    assert _gist("a summary with no terminal punctuation") == \
        "a summary with no terminal punctuation"


def test_gist_single_sentence_unchanged():
    assert _gist("One sentence only.") == "One sentence only."

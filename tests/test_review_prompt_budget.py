"""Review prompt budget: the pieces that keep per-review cost bounded —
story-so-far gisting (and, in later commits, the per-persona excerpt budget
and the system-block layout)."""

from server.routers.review import FOCUS_PROMPTS, _excerpt_budget, _gist


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


def test_excerpt_budget_light_for_craft_personas():
    for focus in ("Literary Agent", "Casual Reader", "Philosopher"):
        assert _excerpt_budget(focus, top_k=15) == 6


def test_excerpt_budget_full_for_canon_personas():
    assert _excerpt_budget("Hard-Core Reader", top_k=15) == 17
    assert _excerpt_budget("What-If Explorer", top_k=15) == 17


def test_excerpt_budget_never_exceeds_configured_top_k():
    # a small TOP_K_RESULTS keeps its own ceiling for every persona
    assert _excerpt_budget("Literary Agent", top_k=3) == 5
    assert _excerpt_budget("Hard-Core Reader", top_k=3) == 5


def test_excerpt_budget_covers_every_persona():
    for focus in FOCUS_PROMPTS:
        assert 1 <= _excerpt_budget(focus, top_k=15) <= 17

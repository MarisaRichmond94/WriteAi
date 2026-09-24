"""Review-experience presets: registry integrity, the aug31 reconstruction,
selection precedence, and effort resolution."""

from server.review_presets import (EFFORT_CHOICES, presets, resolve_effort,
                                   resolve_preset)
from server.routers.review import (FOCUS_PROMPTS, REVIEW_SYSTEM,
                                   _excerpt_budget, _trim_upcoming)


def test_registry_has_the_three_arms():
    assert set(presets()) == {"current", "aug31", "aug31-guarded"}


def test_current_preset_mirrors_live_constants():
    p = presets()["current"]
    assert p.system_base is REVIEW_SYSTEM
    assert _excerpt_budget("Literary Agent", 15, p) == 10
    assert _excerpt_budget("Casual Reader", 15, p) == 6
    assert _excerpt_budget("Hard-Core Reader", 15, p) == 17
    assert p.gist_story_notes and p.upcoming_gist
    assert p.first_appearance_gate
    assert p.effort == "cfg"


def test_aug31_restores_the_pre_september_shape():
    p = presets()["aug31"]
    # full excerpt budget for every persona, Literary Agent included
    for focus in FOCUS_PROMPTS:
        assert _excerpt_budget(focus, 15, p) == 17
    assert not p.gist_story_notes
    assert p.upcoming_window is None and not p.upcoming_gist
    assert "Literary Agent" in p.forward_personas
    assert p.digest_keep_full_books == 0
    assert not p.first_appearance_gate
    assert p.effort == "none"
    # the short two-paragraph system prompt: none of the September rules
    for marker in ("Chronology is a hard rule", "FIRST APPEARANCE",
                   "granularity", "800-1,200"):
        assert marker not in p.system_base
    assert p.quote_instruction is None      # Explore's verbatim quote rules


def test_aug31_guarded_keeps_guardrails_with_august_depth():
    p = presets()["aug31-guarded"]
    assert p.system_base is REVIEW_SYSTEM   # all September rules present
    for focus in FOCUS_PROMPTS:
        assert _excerpt_budget(focus, 15, p) == 17
    assert not p.gist_story_notes
    assert "Literary Agent" not in p.forward_personas
    assert p.first_appearance_gate
    assert p.digest_keep_full_books == 1
    assert p.effort == "none"


def test_uncapped_window_returns_lines_whole():
    lines = [f"- (Ch {n}) x" for n in range(30, 95)]
    assert _trim_upcoming(lines, window=None) == lines
    assert len(_trim_upcoming(lines, window=10)) == 11


def test_resolve_preset_precedence_and_fallback():
    assert resolve_preset("aug31", "current").name == "aug31"
    assert resolve_preset(None, "aug31-guarded").name == "aug31-guarded"
    assert resolve_preset("no-such", "also-bad").name == "current"
    assert resolve_preset(None, "").name == "current"


def test_resolve_effort_precedence():
    reg = presets()
    # request wins over everything
    assert resolve_effort("max", reg["aug31"], "medium") == "max"
    # "none" from request or preset means uncapped
    assert resolve_effort("none", reg["current"], "medium") is None
    assert resolve_effort(None, reg["aug31"], "medium") is None
    # current follows the env var
    assert resolve_effort(None, reg["current"], "high") == "high"
    assert resolve_effort(None, reg["current"], "") is None


def test_effort_choices_cover_api_levels_plus_uncapped():
    assert set(EFFORT_CHOICES) == {"low", "medium", "high", "xhigh", "max",
                                   "none"}

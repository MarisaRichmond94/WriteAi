"""Review prompt budget: the pieces that keep per-review cost bounded —
story-so-far gisting (and, in later commits, the per-persona excerpt budget
and the system-block layout)."""

from types import SimpleNamespace

from server.routers.review import (FOCUS_PROMPTS, _excerpt_budget, _gist,
                                   _question)
from src.answerer import Answerer
from src.query_router import QueryPlan


def _answerer(**overrides):
    cfg = SimpleNamespace(anthropic_api_key="test-key",
                          query_model="claude-sonnet-5",
                          enable_prompt_cache_v2=True,
                          prompt_cache_ttl="1h",
                          api_read_timeout_s=5.0)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return Answerer(cfg)


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


def test_question_defaults_to_the_review_ask():
    assert _question("", "Literary Agent", []) == \
        "Give your review of this chapter as a Literary Agent."


def test_question_opening_note_steers_rather_than_replaces():
    q = _question("Watch the pacing in the middle third.", "Casual Reader", [])
    assert q.startswith("Give your review of this chapter as a Casual Reader.")
    assert "Watch the pacing in the middle third." in q


def test_question_later_turns_are_verbatim():
    history = [{"role": "user", "content": "hi"},
               {"role": "assistant", "content": "review text"}]
    assert _question("Does the twist land?", "Casual Reader", history) == \
        "Does the twist land?"


def test_system_block_layout_and_breakpoint_budget():
    a = _answerer()
    req = a.build_request(
        QueryPlan(question="q", qtype="general"), [], [],
        history=[{"role": "user", "content": "hi"},
                 {"role": "assistant", "content": "there"}],
        system_extra="STABLE BIBLES", system_extra_tail="PROFILES",
        system_volatile="PERSONA", effort="medium")
    texts = [b["text"] for b in req["system"]]
    assert "STABLE BIBLES" in texts[0]        # stable prefix holds the bibles
    assert texts[1] == "PROFILES"             # tail block sits between them
    assert texts[2] == "PERSONA"              # volatile block stays last
    assert all("cache_control" in b for b in req["system"])
    marked_history = sum(
        1 for m in req["messages"]
        if isinstance(m.get("content"), list)
        and any("cache_control" in b for b in m["content"]
                if isinstance(b, dict)))
    # stable + tail + volatile + history marker: exactly the API's max 4
    assert len(req["system"]) + marked_history == 4
    assert req["output_config"] == {"effort": "medium"}


def test_empty_tail_keeps_legacy_block_shape():
    a = _answerer(enable_prompt_cache_v2=False)
    req = a.build_request(QueryPlan(question="q", qtype="general"), [], [])
    assert len(req["system"]) == 1
    assert "output_config" not in req

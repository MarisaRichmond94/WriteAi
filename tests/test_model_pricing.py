"""Every model the UI offers must have a pricing entry (LOOM-119).

The backend has no model allowlist — whatever id the dropdown sends goes
straight to the Anthropic SDK — so a model missing from PRICING_PER_MTOK is
still *called*, and only its cost is wrong. The fallback rate is cheaper than
the models most likely to be missing (a new flagship), so the failure
under-reports spend: the number moves in the direction that makes a feature
look affordable.

That is exactly what happened. `claude-opus-5` shipped in neither table, and
the only thing guarding the invariant was a comment in models.ts asking people
to remember. This test is the thing that actually holds it.

The frontend list is parsed out of the TypeScript rather than restated here on
purpose: a hand-copied list in the test would drift the same way, and would
then pass while the real dropdown was wrong.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_model_pricing -v
"""

from __future__ import annotations

import logging
import re
import unittest

from config import REPO_ROOT
from src.extractor import PRICING_PER_MTOK, _pricing_for, _warned_unpriced

MODELS_TS = REPO_ROOT / "frontend" / "src" / "lib" / "models.ts"

FALLBACK = (1.00, 5.00)


def _source() -> str:
    return MODELS_TS.read_text(encoding="utf-8")


def _ids_in_block(source: str, const_name: str) -> list[str]:
    """The `id:` values inside `export const <const_name>: ... = [ ... ]`."""
    match = re.search(
        rf"export const {const_name}\s*:[^=]*=\s*\[(.*?)\]", source, re.S)
    if not match:
        raise AssertionError(f"could not find {const_name} in {MODELS_TS}")
    return re.findall(r"""id:\s*["']([^"']+)["']""", match.group(1))


def _const(source: str, const_name: str) -> str:
    match = re.search(rf"""export const {const_name} = ["']([^"']+)["']""",
                      source)
    if not match:
        raise AssertionError(f"could not find {const_name} in {MODELS_TS}")
    return match.group(1)


class OfferedModelsArePriced(unittest.TestCase):
    def setUp(self):
        self.src = _source()

    def test_every_offered_chat_model_is_priced(self):
        offered = _ids_in_block(self.src, "CHAT_MODELS")
        self.assertTrue(offered, "CHAT_MODELS parsed as empty — regex drifted")
        missing = [m for m in offered if m not in PRICING_PER_MTOK]
        self.assertEqual(missing, [], (
            f"models offered in the UI with no PRICING_PER_MTOK entry: {missing}. "
            "Their spend would be logged at the fallback rate, which is wrong "
            "and silently cheap. Add them to src/extractor.py."))

    def test_default_models_are_priced(self):
        for name in ("DEFAULT_QUERY_MODEL", "DEFAULT_EXTRACTION_MODEL"):
            with self.subTest(const=name):
                model = _const(self.src, name)
                self.assertIn(model, PRICING_PER_MTOK, (
                    f"{name} is {model!r}, which has no pricing entry — every "
                    "call made with the default would be costed wrongly."))

    def test_python_and_typescript_model_lists_agree(self):
        """The API serves the Python list; WriteAI's own pane renders the TS
        one; Loom renders whatever the API serves. Three consumers, so the two
        lists must not fork — a model offered in one app and not the other is a
        difference nobody would notice until a spend figure looked wrong."""
        from server.routers.settings import CHAT_MODELS as PY_MODELS

        ts_ids = _ids_in_block(self.src, "CHAT_MODELS")
        py_ids = [m["id"] for m in PY_MODELS]
        self.assertEqual(py_ids, ts_ids)

    def test_python_chat_models_are_priced(self):
        from server.routers.settings import CHAT_MODELS as PY_MODELS

        missing = [m["id"] for m in PY_MODELS if m["id"] not in PRICING_PER_MTOK]
        self.assertEqual(missing, [], (
            f"models served by GET /api/models with no pricing entry: {missing}"))

    def test_python_default_is_offered_and_priced(self):
        from server.routers.settings import CHAT_MODELS as PY_MODELS
        from server.routers.settings import DEFAULT_CHAT_MODEL

        self.assertIn(DEFAULT_CHAT_MODEL, [m["id"] for m in PY_MODELS])
        self.assertIn(DEFAULT_CHAT_MODEL, PRICING_PER_MTOK)

    def test_api_default_is_the_model_a_null_request_actually_gets(self):
        """`GET /api/models` advertises a default; a request with `model: null`
        runs on `cfg.query_model`. Those must be the same string.

        They were not: the endpoint read a settings key that does not exist,
        fell through to DEFAULT_CHAT_MODEL, and advertised claude-sonnet-5
        while answers actually ran on claude-sonnet-4-6. Nothing errors when
        they disagree — the picker shows one model and the bill is for
        another."""
        from unittest.mock import patch

        from server.routers import settings as mod

        class FakeCfg:
            query_model = "claude-sonnet-4-6"   # priced, not in CHAT_MODELS

        with patch.object(mod, "get_state", lambda: type("S", (), {"cfg": FakeCfg})()):
            payload = mod.list_models()

        self.assertEqual(payload["default"], "claude-sonnet-4-6")
        self.assertIn("claude-sonnet-4-6", [m["id"] for m in payload["models"]],
                      "the configured model must be selectable, or the picker "
                      "cannot show what is actually in use")

    def test_an_unpriced_configured_model_is_not_offered(self):
        """A configured model with no pricing entry would answer fine and cost
        the wrong amount — the exact failure this suite exists to prevent."""
        from unittest.mock import patch

        from server.routers import settings as mod

        class FakeCfg:
            query_model = "claude-not-priced-9"

        with patch.object(mod, "get_state", lambda: type("S", (), {"cfg": FakeCfg})()):
            payload = mod.list_models()

        self.assertNotIn("claude-not-priced-9", [m["id"] for m in payload["models"]])
        self.assertEqual(payload["default"], mod.DEFAULT_CHAT_MODEL)

    def test_the_two_defaults_agree(self):
        """The API's default (Loom reads this) and the frontend's default
        (WriteAI's own pane reads this) live in different files and different
        languages. Drift between them is invisible — both apps work, they just
        quietly bill at different rates for the same question."""
        from server.routers.settings import DEFAULT_CHAT_MODEL

        self.assertEqual(DEFAULT_CHAT_MODEL, _const(self.src, "DEFAULT_QUERY_MODEL"))

    def test_opus_5_priced_at_its_real_rate(self):
        """The specific regression. Opus 5 is $5/$25; the generic fallback is
        $1/$5 and answerer.py's old one was $3/$15 — both under-report."""
        self.assertEqual(PRICING_PER_MTOK.get("claude-opus-5"), (5.00, 25.00))


class Sonnet5IntroPricingFlips(unittest.TestCase):
    """Sonnet 5's intro pricing ($2/$10) ends 2026-08-31. The flip must be
    date-driven inside _pricing_for — a table entry someone has to remember
    to edit on Sept 1 would under-report every Sonnet 5 call by a third,
    silently, in the direction that makes spend look fine."""

    def _on(self, iso_day: str):
        import datetime as real_dt
        from unittest.mock import patch

        class FakeDate(real_dt.date):
            @classmethod
            def today(cls):
                return real_dt.date.fromisoformat(iso_day)

        with patch("src.extractor.date", FakeDate):
            return _pricing_for("claude-sonnet-5")

    def test_intro_rate_through_august_31(self):
        self.assertEqual(self._on("2026-08-31"), (2.00, 10.00))

    def test_standard_rate_from_september_1(self):
        self.assertEqual(self._on("2026-09-01"), (3.00, 15.00))

    def test_other_models_are_untouched_by_the_boundary(self):
        import datetime as real_dt
        from unittest.mock import patch

        class FakeDate(real_dt.date):
            @classmethod
            def today(cls):
                return real_dt.date(2026, 9, 1)

        with patch("src.extractor.date", FakeDate):
            self.assertEqual(_pricing_for("claude-haiku-4-5"), (1.00, 5.00))


class UnpricedModelIsLoud(unittest.TestCase):
    def setUp(self):
        _warned_unpriced.clear()   # the warning is once-per-process

    def test_unpriced_model_warns_rather_than_passing_silently(self):
        with self.assertLogs("src.extractor", level=logging.WARNING) as cm:
            price = _pricing_for("claude-not-a-real-model-9")
        self.assertEqual(price, FALLBACK,
                         "fallback rate changed without updating this test")
        self.assertTrue(any("no pricing entry" in line for line in cm.output),
                        "an unpriced model must name itself in a warning — a "
                        "silent fallback is how this bug survived")

    def test_warning_fires_once_per_model(self):
        with self.assertLogs("src.extractor", level=logging.WARNING) as cm:
            _pricing_for("claude-not-a-real-model-9")
            _pricing_for("claude-not-a-real-model-9")
        self.assertEqual(len(cm.output), 1,
                         "a per-call warning would flood the log on every "
                         "chunk of a streamed answer")

    def test_known_model_does_not_warn(self):
        logger = logging.getLogger("src.extractor")
        with self.assertLogs(logger, level=logging.WARNING) as cm:
            logger.warning("sentinel")     # assertLogs needs >= 1 record
            self.assertEqual(_pricing_for("claude-opus-5"), (5.00, 25.00))
        self.assertEqual([l for l in cm.output if "no pricing entry" in l], [])


if __name__ == "__main__":
    unittest.main()

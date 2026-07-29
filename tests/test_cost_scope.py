"""Regression tests for spend that used to vanish from the cost ledger.

Both streaming surfaces logged their ledger line after the stream loop, so a
request that died partway through logged nothing at all. The API still bills
for the prompt it processed and the output it produced before the failure, so
the dashboard quietly understated the real spend — and a writer looking at a
blank review had no way to see what it had cost her.

Observed 2026-07-28: a Book 3 Chapter 24 review stalled ten minutes into the
stream and hit a read timeout. The ledger recorded $0.00 for reviews that day.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_cost_scope -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src import costlog


class _FakeAnswerer:
    """Stands in for an Answerer: cumulative counters and a derived cost."""

    model = "claude-sonnet-5"

    def __init__(self) -> None:
        self.usage = {"input_tokens": 0, "output_tokens": 0,
                      "cache_write_tokens": 0, "cache_read_tokens": 0}
        self.actual_cost_usd = 0.0

    def bill(self, *, inp: int = 0, out: int = 0, cache_write: int = 0,
             cost: float = 0.0) -> None:
        self.usage["input_tokens"] += inp
        self.usage["output_tokens"] += out
        self.usage["cache_write_tokens"] += cache_write
        self.actual_cost_usd = round(self.actual_cost_usd + cost, 4)


class _Cfg:
    cost_log_enabled = True


class CostScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._real_path = costlog._PATH
        costlog._PATH = Path(self._tmp.name) / "cost.jsonl"
        self.addCleanup(lambda: setattr(costlog, "_PATH", self._real_path))

    def _lines(self) -> list[dict]:
        if not costlog._PATH.exists():
            return []
        return [json.loads(ln) for ln in
                costlog._PATH.read_text(encoding="utf-8").splitlines() if ln]

    def test_completed_stream_logs_done(self):
        a = _FakeAnswerer()
        with costlog.cost_scope(_Cfg(), surface="review", answerer=a,
                                qtype="general", extra={"focus": "Casual Reader"}):
            a.bill(inp=33000, out=9000, cache_write=52000, cost=0.286)

        line, = self._lines()
        self.assertEqual(line["state"], "done")
        self.assertEqual(line["surface"], "review")
        self.assertEqual(line["cost_usd"], 0.286)
        self.assertEqual(line["focus"], "Casual Reader")
        self.assertNotIn("error", line)

    def test_failed_stream_still_logs_partial_spend(self):
        """The bug: this used to write nothing."""
        a = _FakeAnswerer()
        with self.assertRaises(TimeoutError):
            with costlog.cost_scope(_Cfg(), surface="review", answerer=a,
                                    qtype="general", extra={"focus": "Literary Agent"}):
                a.bill(inp=33000, cache_write=52000, cost=0.196)
                raise TimeoutError("The read operation timed out")

        line, = self._lines()
        self.assertEqual(line["state"], "failed")
        self.assertEqual(line["cost_usd"], 0.196)
        self.assertIn("timed out", line["error"])
        # the tokens the API actually processed are on the line, not zeroed
        self.assertEqual(line["input_tokens"], 33000)
        self.assertEqual(line["cache_write_tokens"], 52000)

    def test_client_disconnect_logs_aborted(self):
        """Closing the tab kills the generator with GeneratorExit, which is a
        BaseException — an `except Exception` guard would miss it."""
        def stream():
            a = _FakeAnswerer()
            with costlog.cost_scope(_Cfg(), surface="chat", answerer=a,
                                    qtype="general"):
                a.bill(inp=5000, out=200, cost=0.012)
                yield "partial answer"
                yield "never reached"

        g = stream()
        next(g)
        g.close()

        line, = self._lines()
        self.assertEqual(line["state"], "aborted")
        self.assertEqual(line["cost_usd"], 0.012)
        self.assertEqual(line["error"], "client disconnected")

    def test_scope_diffs_cumulative_counters(self):
        """An Answerer's counters are cumulative across calls; the line must
        carry this request's share, not the running total."""
        a = _FakeAnswerer()
        a.bill(inp=1000, out=100, cost=0.05)          # an earlier turn
        with costlog.cost_scope(_Cfg(), surface="chat", answerer=a):
            a.bill(inp=400, out=50, cost=0.02)

        line, = self._lines()
        self.assertEqual(line["input_tokens"], 400)
        self.assertEqual(line["output_tokens"], 50)
        self.assertEqual(line["cost_usd"], 0.02)

    def test_ledger_failure_never_breaks_the_request(self):
        costlog._PATH = Path(self._tmp.name) / "no-such-dir" / "x" / "cost.jsonl"
        a = _FakeAnswerer()
        with costlog.cost_scope(_Cfg(), surface="review", answerer=a):
            a.bill(inp=10, cost=0.001)   # must not raise


if __name__ == "__main__":
    unittest.main()

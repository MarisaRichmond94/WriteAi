"""Tests for the enrichment rerun queue and the mid-run ingest guard.

The 2026-08-12 incident had two halves: an enrichment run kept writing
chapter rows from a numbering snapshot an ingest was rewriting underneath it,
and the forced corrective run that fired during it was silently dropped.
These tests cover the two mechanisms that close that: request_rerun (queued
triggers survive) and the ingest-generation check (a pass stops writing
rather than trust a stale snapshot).

Run from the repo root:
    .venv/bin/python -m unittest tests.test_enrich_rerun -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import enrich  # noqa: E402
from server.enrich import EnrichmentRunner, _IngestInterrupted  # noqa: E402
from server.routers import books  # noqa: E402


class RerunQueueTest(unittest.TestCase):

    def setUp(self):
        self.runner = EnrichmentRunner()

    def test_request_and_consume_roundtrip(self):
        self.assertFalse(self.runner.rerun_pending)
        self.runner.request_rerun("numbering changed")
        self.assertTrue(self.runner.rerun_pending)
        self.assertEqual(self.runner.consume_rerun(), "numbering changed")
        self.assertFalse(self.runner.rerun_pending)
        self.assertIsNone(self.runner.consume_rerun())

    def _drive(self, passes_that_request_rerun=()):
        """Run the driver with _run_once stubbed; returns pass count."""
        counted = {"passes": 0}

        def fake_pass(_db, _cfg, _canon):
            counted["passes"] += 1
            if counted["passes"] in passes_that_request_rerun:
                self.runner.request_rerun(f"pass {counted['passes']}")

        self.runner._run_once = fake_pass
        self.runner._run("db", "cfg", "canon")
        return counted["passes"]

    def test_no_rerun_means_one_pass(self):
        self.assertEqual(self._drive(), 1)

    def test_queued_rerun_runs_immediately(self):
        self.assertEqual(self._drive(passes_that_request_rerun={1}), 2)
        self.assertFalse(self.runner.rerun_pending)

    def test_rerun_queued_each_pass_keeps_driving(self):
        self.assertEqual(self._drive(passes_that_request_rerun={1, 2}), 3)

    def test_rerun_waits_out_an_active_ingest(self):
        """With an ingest mid-flight the driver must NOT restart — the rerun
        stays queued for the post-ingest watcher, which starts it once the
        subprocess and its post-processing are done."""
        self.runner.ingest_active = lambda: True
        self.assertEqual(self._drive(passes_that_request_rerun={1}), 1)
        self.assertTrue(self.runner.rerun_pending)


class IngestGenerationTest(unittest.TestCase):

    def setUp(self):
        self.runner = EnrichmentRunner()

    def test_unchanged_generation_passes(self):
        gen = self.runner._ingest_generation
        self.runner._check_ingest_generation(gen, remaining=5)  # no raise

    def test_ingest_mid_run_interrupts(self):
        gen = self.runner._ingest_generation
        self.runner.note_ingest_started()
        with self.assertRaises(_IngestInterrupted):
            self.runner._check_ingest_generation(gen, remaining=5)


class AutoEnrichQueueTest(unittest.TestCase):
    """_auto_enrich must queue a rerun, never drop the trigger, when a run is
    already in flight."""

    class _FakeRunner:
        def __init__(self, running):
            self.running = running
            self.queued = []

        def request_rerun(self, reason):
            self.queued.append(reason)

    def setUp(self):
        self._runner = enrich.runner
        self._settings = books.writer_store.ui_settings
        self._log_event = books.audit.log_event
        books.audit.log_event = lambda *a, **k: None
        self.addCleanup(self._restore)

    def _restore(self):
        enrich.runner = self._runner
        books.writer_store.ui_settings = self._settings
        books.audit.log_event = self._log_event

    def test_trigger_during_run_is_queued(self):
        books.writer_store.ui_settings = lambda: {"auto_enrich_enabled": True}
        fake = self._FakeRunner(running=True)
        enrich.runner = fake
        # Were the early return missing, _auto_enrich would hit get_state()
        # and fail loudly — reaching the assert proves the trigger was queued
        # instead of starting (or dropping) a run.
        books._auto_enrich("chapter numbering change")
        self.assertEqual(fake.queued, ["chapter numbering change"])

    def test_disabled_auto_enrich_queues_nothing(self):
        books.writer_store.ui_settings = lambda: {"auto_enrich_enabled": False}
        fake = self._FakeRunner(running=True)
        enrich.runner = fake
        books._auto_enrich("chapter numbering change")
        self.assertEqual(fake.queued, [])


if __name__ == "__main__":
    unittest.main()

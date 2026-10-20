"""Fail-closed, no-database regression checks for CI due-tick stage BEGIN markers."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TIMING = ROOT / "apps/api/tests/ci_due_tick_stage_timing.py"
TEST = ROOT / "apps/api/tests/test_external_document_source_due_tick_observation_concurrency_postgres.py"
WORKFLOW = ROOT / ".github/workflows/postgres-concurrency-regressions.yml"

spec = importlib.util.spec_from_file_location("ci_due_tick_stage_timing_policy", TIMING)
assert spec is not None and spec.loader is not None
timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)


class DueTickStageEntryMarkerTests(unittest.TestCase):
    def _load(self, path: Path):
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]

    def test_begin_marker_precedes_work_and_end_preserves_duration_schema(self):
        with tempfile.TemporaryDirectory() as dirname:
            out = Path(dirname) / "stage.jsonl"
            with patch.object(timing, "_LOG_PATH", str(out)), patch.dict(
                os.environ,
                {"APP_ENV": "test", "EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST": "1"},
            ):
                with timing.ci_due_tick_stage("same_tick_schedule"):
                    self.assertEqual(self._load(out), [
                        {"event": "ci_due_tick_stage_begin", "stage": "same_tick_schedule"}
                    ])
                rows = self._load(out)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["event"], "ci_due_tick_stage")
            self.assertEqual(rows[1]["stage"], "same_tick_schedule")
            self.assertEqual(set(rows[1]), {"event", "stage", "elapsed_seconds"})
            self.assertGreaterEqual(rows[1]["elapsed_seconds"], 0)

    def test_exception_keeps_safe_completed_record_but_never_exception_text(self):
        with tempfile.TemporaryDirectory() as dirname:
            out = Path(dirname) / "stage.jsonl"
            with patch.object(timing, "_LOG_PATH", str(out)), patch.dict(
                os.environ,
                {"APP_ENV": "test", "EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST": "1"},
            ):
                with self.assertRaisesRegex(RuntimeError, "DO_NOT_LOG_PRIVATE_TEST_ERROR"):
                    with timing.ci_due_tick_stage("disable_race_schedule"):
                        raise RuntimeError("DO_NOT_LOG_PRIVATE_TEST_ERROR")
                rows = self._load(out)
            self.assertEqual(
                [x["event"] for x in rows],
                ["ci_due_tick_stage_begin", "ci_due_tick_stage"],
            )
            self.assertNotIn("DO_NOT_LOG_PRIVATE_TEST_ERROR", out.read_text(encoding="utf-8"))

    def test_nested_stages_emit_ordered_begin_end_pairs(self):
        with tempfile.TemporaryDirectory() as dirname:
            out = Path(dirname) / "stage.jsonl"
            with patch.object(timing, "_LOG_PATH", str(out)), patch.dict(
                os.environ,
                {"APP_ENV": "test", "EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST": "1"},
            ):
                with timing.ci_due_tick_stage("same_tick_seed"):
                    with timing.ci_due_tick_stage("sharepoint_v1_admit"):
                        pass
            self.assertEqual(
                [(x["event"], x["stage"]) for x in self._load(out)],
                [
                    ("ci_due_tick_stage_begin", "same_tick_seed"),
                    ("ci_due_tick_stage_begin", "sharepoint_v1_admit"),
                    ("ci_due_tick_stage", "sharepoint_v1_admit"),
                    ("ci_due_tick_stage", "same_tick_seed"),
                ],
            )

    def test_unapproved_label_refuses_before_any_write(self):
        with tempfile.TemporaryDirectory() as dirname:
            out = Path(dirname) / "stage.jsonl"
            with patch.object(timing, "_LOG_PATH", str(out)), patch.dict(
                os.environ,
                {"APP_ENV": "test", "EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST": "1"},
            ):
                with self.assertRaises(ValueError):
                    with timing.ci_due_tick_stage("CUSTOMER_CLAIM_ID-123"):
                        pass
            self.assertFalse(out.exists())

    def test_no_stage_output_without_both_ci_flags(self):
        with tempfile.TemporaryDirectory() as dirname:
            out = Path(dirname) / "stage.jsonl"
            with patch.object(timing, "_LOG_PATH", str(out)):
                for env in (
                    {"APP_ENV": "dev", "EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST": "1"},
                    {"APP_ENV": "test", "EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST": "0"},
                ):
                    with patch.dict(os.environ, env):
                        with timing.ci_due_tick_stage("same_tick_schedule"):
                            pass
            self.assertFalse(out.exists())

    def test_protect_real_races_and_existing_error_gate(self):
        code = TEST.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(code.count('with ci_due_tick_stage("same_tick_schedule"):'), 1)
        self.assertEqual(code.count('with ci_due_tick_stage("disable_race_schedule"):'), 1)
        self.assertIn('with ci_due_tick_stage("same_tick_workers"):', code)
        self.assertIn('with ci_due_tick_stage("disable_race_workers"):', code)
        self.assertIn('assert sorted(result[0] for result in results) == ["conflict", "ok"]', code)
        self.assertIn('assert len(rows) == 1', code)
        self.assertIn('assert disable_result[1] == "ok"', code)
        self.assertIn('assert consume_result[1] in {"ok", "conflict"}', code)
        self.assertIn('-o faulthandler_timeout=180', workflow)
        self.assertIn('PGOPTIONS: "-c lock_timeout=300000 -c statement_timeout=600000"', workflow)
        self.assertIn('exit "$pytest_exit"', workflow)
        self.assertIn("ci_due_tick_stage_begin", TIMING.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

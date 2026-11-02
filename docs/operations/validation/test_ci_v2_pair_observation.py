"""Fixed-clock, offline, invented GitHub DTOs; never dispatches workflows."""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("ci_pair", Path(__file__).with_name("ci_v2_pair_observation.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(candidate=False):
    origin = datetime(2026, 11, 2, tzinfo=timezone.utc) + timedelta(hours=int(candidate))
    def stamp(seconds):
        return (origin + timedelta(seconds=seconds)).isoformat()
    def step(name, start, end):
        return {"name": name, "conclusion": "success", "started_at": stamp(start), "completed_at": stamp(end)}
    def job(name, identity, start, end, steps=()):
        return {"id": identity, "name": name, "status": "completed", "conclusion": "success", "started_at": stamp(start), "completed_at": stamp(end), "labels": ["ubuntu-latest"], "steps": list(steps)}
    start, end = (240, 360) if candidate else (60, 180)
    jobs = [job("Classify backend changes", 1, 0, 1), job("Backend tests", 2, end, end + 1)]
    narrow = job("Backend changed-test verification", 3, 0, 0)
    narrow["conclusion"] = "skipped"
    jobs.append(narrow)
    if candidate:
        jobs.append(job("Backend collection manifest", 4, 60, 240, [step("Install backend dependencies", 60, 90), step("Collect exact-commit backend manifest", 90, 230), step("Upload current-run collection manifest", 230, 240)]))
    for n in range(64):
        steps = [step("Install backend dependencies", start, start + 15), step("Run backend test shard", start + 20, end)]
        if candidate:
            steps.append(step("Download current-run collection manifest", start + 15, start + 20))
        jobs.append(job(f"Backend tests shard {n}", 100 + n, start, end, steps))
    return {"id": 2 if candidate else 1, "event": "workflow_dispatch", "run_attempt": 1, "status": "completed", "conclusion": "success", "head_sha": ("b" if candidate else "a") * 40, "created_at": stamp(0), "jobs": jobs, "observed_competing_workflows": []}


def preflight():
    return {"baseline_sha": "a" * 40, "candidate_sha": "b" * 40, "app_tree": "c" * 40, "candidate_app_tree": "c" * 40, "matched_application_tests_locks": True, "classifier_unchanged": True}


class PairObservationTests(unittest.TestCase):
    def test_success_includes_serial_producer_and_never_claims_acceptance(self):
        result = module.compare_pair(preflight(), fixture(), fixture(True))
        self.assertEqual(result["baseline"]["shard_runner_minutes"], 128)
        self.assertEqual(result["candidate"]["producer_runner_minutes"], 3)
        self.assertEqual(result["candidate"]["backend_runner_minutes_including_producer"], 131)
        self.assertEqual(result["baseline"]["dispatch_to_first_shard_start_minutes"], 1)
        self.assertEqual(result["candidate"]["dispatch_to_producer_completion_minutes"], 4)
        self.assertAlmostEqual(result["candidate"]["producer_collection_and_manifest_step_minutes"], 140 / 60)
        self.assertAlmostEqual(result["candidate"]["artifact_transfer_step_minutes"], (10 + 64 * 5) / 60)
        self.assertAlmostEqual(result["observed_backend_cost_change_percent"], 3 / 128 * 100)
        self.assertFalse(result["acceptance_established"])
        self.assertFalse(result["median_or_p95_established"])
        self.assertFalse(result["exact_collected_node_ids_and_outcomes_verified"])
        self.assertFalse(result["collection_only_cost_measured"])
        self.assertFalse(result["cache_and_runner_image_parity_verified"])

    def test_missing_duplicate_skipped_or_failed_shards_never_create_success_metrics(self):
        variants = []
        missing = fixture(); missing["jobs"].pop(); variants.append(missing)
        duplicate = fixture(); duplicate["jobs"].append(copy.deepcopy(duplicate["jobs"][-1])); variants.append(duplicate)
        for conclusion in ("skipped", "failure", "cancelled", None):
            value = fixture(); value["jobs"][-1]["conclusion"] = conclusion; variants.append(value)
        for value in variants:
            with self.subTest(value=value["jobs"][-1]["conclusion"]), self.assertRaises(ValueError):
                module.summarize_run(value, "a" * 40, candidate=False)

    def test_producer_or_gate_failures_and_wrong_job_graph_fail_closed(self):
        for name in ("Backend collection manifest", "Backend tests", "Classify backend changes"):
            for mode in ("remove", "fail"):
                value = fixture(True)
                row = next(j for j in value["jobs"] if j["name"] == name)
                if mode == "remove": value["jobs"].remove(row)
                else: row["conclusion"] = "failure"
                with self.subTest(name=name, mode=mode), self.assertRaises(ValueError):
                    module.summarize_run(value, "b" * 40, candidate=True)
        with self.assertRaises(ValueError):
            module.summarize_run(fixture(True), "b" * 40, candidate=False)

    def test_wrong_commit_event_attempt_and_incomplete_run_fail_closed(self):
        for key, bad in (("head_sha", "d" * 40), ("event", "pull_request"), ("run_attempt", 2), ("run_attempt", True), ("status", "in_progress"), ("conclusion", "cancelled")):
            value = fixture(); value[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.summarize_run(value, "a" * 40, candidate=False)

    def test_broken_timestamps_runner_or_executed_steps_are_rejected(self):
        for key, bad in (("started_at", "bad"), ("completed_at", "2026-11-01T00:00:00Z"), ("started_at", "2026-11-02T00:01:00"), ("labels", ["other-runner"]), ("steps", []), ("id", 100)):
            value = fixture(); value["jobs"][-1][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                module.summarize_run(value, "a" * 40, candidate=False)

    def test_source_mismatch_and_overlapping_pair_are_not_compared(self):
        for key, bad in (("candidate_app_tree", "d" * 40), ("matched_application_tests_locks", False), ("classifier_unchanged", False), ("baseline_sha", "bad")):
            value = preflight(); value[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.compare_pair(value, fixture(), fixture(True))
        candidate = fixture(True); candidate["created_at"] = "2026-11-02T00:02:00Z"
        with self.assertRaises(ValueError):
            module.compare_pair(preflight(), fixture(), candidate)

    def test_competing_workflows_are_visible_not_accepted_as_controlled(self):
        candidate = fixture(True); candidate["observed_competing_workflows"] = [{"id": 999}]
        result = module.compare_pair(preflight(), fixture(), candidate)
        self.assertFalse(result["isolation_observed"])
        self.assertFalse(result["acceptance_established"])

    def test_missing_isolation_evidence_and_balanced_step_substitution_are_rejected(self):
        baseline = fixture(); del baseline["observed_competing_workflows"]
        with self.assertRaises(ValueError):
            module.compare_pair(preflight(), baseline, fixture(True))
        baseline = fixture()
        # A missing step on one shard cannot be balanced by a duplicate elsewhere.
        baseline["jobs"][-1]["steps"].pop()
        baseline["jobs"][-2]["steps"].append(copy.deepcopy(baseline["jobs"][-2]["steps"][-1]))
        with self.assertRaises(ValueError):
            module.compare_pair(preflight(), baseline, fixture(True))

    def test_producer_collection_upload_and_consumer_download_must_execute(self):
        for name in ("Collect exact-commit backend manifest", "Upload current-run collection manifest", "Download current-run collection manifest"):
            candidate = fixture(True)
            target = next(j for j in candidate["jobs"] if any(s["name"] == name for s in j["steps"]))
            next(s for s in target["steps"] if s["name"] == name)["conclusion"] = "skipped"
            with self.subTest(name=name), self.assertRaises(ValueError):
                module.compare_pair(preflight(), fixture(), candidate)

    def test_required_step_timing_cannot_escape_its_job(self):
        for field, value in (("started_at", "2026-11-02T00:00:59Z"), ("completed_at", "2026-11-02T00:03:01Z")):
            baseline = fixture(); baseline["jobs"][-1]["steps"][-1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.compare_pair(preflight(), baseline, fixture(True))

    def test_cli_invalid_input_returns_nonzero_without_partial_json_or_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fiction.json"; path.write_text("{}")
            output = io.StringIO()
            with patch.object(sys, "argv", ["ci_pair", str(path), str(path), str(path)]), contextlib.redirect_stdout(output):
                self.assertEqual(module.main(), 1)
            self.assertEqual(output.getvalue(), "ci_pair_observation_failed_closed\n")


if __name__ == "__main__":
    unittest.main()

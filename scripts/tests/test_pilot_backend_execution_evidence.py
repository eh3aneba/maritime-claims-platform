"""Network-free regression coverage for exact-head Full Backend job evidence."""
from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_backend_execution_evidence as evidence  # noqa: E402

REPO = "eh3aneba/maritime-claims-platform"
SHA = "a" * 40
RUN_ID = 321
ATTEMPT = 2


def workflow():
    return {
        "id": RUN_ID, "name": "Full Backend Pre-Merge",
        "head_sha": SHA, "run_attempt": ATTEMPT,
        "html_url": f"https://github.com/{REPO}/actions/runs/{RUN_ID}",
        "status": "completed", "conclusion": "success",
    }


def job(name, id, conclusion="success", *, full=None, bypass=None):
    out = {
        "id": id, "run_id": RUN_ID, "run_attempt": ATTEMPT,
        "name": name, "status": "completed", "conclusion": conclusion,
    }
    if full is not None:
        out["steps"] = [
            {"name": "Verify full backend shards succeeded", "conclusion": full},
            {"name": "Record workflow-only backend bypass", "conclusion": bypass},
        ]
    return out


def scoped():
    return [
        job("Classify backend changes", 1),
        job("Backend tests", 2, full="skipped", bypass="success"),
        job(evidence.SKIPPED_MATRIX_PLACEHOLDER, 3, conclusion="skipped"),
    ]


def full():
    return [
        job("Classify backend changes", 1),
        job("Backend tests", 2, full="success", bypass="skipped"),
        *[job(f"Backend tests shard {i}", i + 10)
          for i in range(64)],
    ]


class BackendExecutionEvidenceTests(unittest.TestCase):
    def evaluate(self, jobs):
        return evidence.evaluate(run=workflow(), jobs=jobs,
                                 repo=REPO, sha=SHA, run_id=RUN_ID)

    def test_scope_bypass_is_explicit_and_never_full_pass(self):
        r = self.evaluate(scoped())
        self.assertEqual(r["execution_mode"], "scoped_skip_verified")
        self.assertEqual(r["backend_shards_executed_and_passed"], 0)
        self.assertFalse(r["full_backend_64_shards_pass"])
        self.assertTrue(r["scope_bypass_explicitly_verified"])
        self.assertFalse(r["pilot_authorized"])

    def test_real_all_64_shards_pass(self):
        r = self.evaluate(full())
        self.assertEqual(r["execution_mode"], "full_64_shards_pass")
        self.assertEqual(r["backend_shards_executed_and_passed"], 64)
        self.assertTrue(r["full_backend_64_shards_pass"])
        self.assertFalse(r["scope_bypass_explicitly_verified"])
        self.assertNotIn("secrets", json.dumps(r))

    def test_missing_failed_duplicate_and_partial_shards_refused(self):
        variants = [
            full()[:-1],
            [*full()[:-1], job("Backend tests shard 63", 73, "failure")],
            [*full()[:-1], job("Backend tests shard 62", 73)],
            [*full()[:-1], job("Backend tests shard 64", 73)],
            [*full()[:-1], job(evidence.SKIPPED_MATRIX_PLACEHOLDER, 73, "skipped")],
        ]
        for jobs in variants:
            with self.assertRaises(evidence.BackendEvidenceError):
                self.evaluate(jobs)

    def test_bypass_only_when_aggregate_explicitly_signals_skip(self):
        for broken in (
            [scoped()[0], job("Backend tests", 2, full="success", bypass="skipped"), scoped()[2]],
            [scoped()[0], job("Backend tests", 2, full="skipped", bypass="skipped"), scoped()[2]],
            [scoped()[0], scoped()[2]],
            [scoped()[0], *scoped()[1:], scoped()[2]],
        ):
            with self.assertRaises(evidence.BackendEvidenceError):
                self.evaluate(broken)

    def test_exact_sha_workflow_and_attempt_guards(self):
        for field, value in (
            ("head_sha", "b" * 40),
            ("name", "Other Workflow"),
            ("html_url", "https://host.invalid/actions/runs/321"),
            ("status", "in_progress"),
            ("conclusion", "failure"),
            ("run_attempt", 0),
        ):
            corrupted = workflow()
            corrupted[field] = value
            with self.assertRaises(evidence.BackendEvidenceError):
                evidence.evaluate(run=corrupted, jobs=full(), repo=REPO,
                                  sha=SHA, run_id=RUN_ID)
        changed = full()
        changed[2]["run_attempt"] = 1
        with self.assertRaises(evidence.BackendEvidenceError):
            self.evaluate(changed)

    def test_attempt_scoped_pagination_uses_only_requested_run(self):
        with patch.object(evidence, "_get", side_effect=[
            workflow(), {"jobs": scoped()},
        ]) as get:
            run, jobs = evidence.fetch(repo=REPO, sha=SHA, run_id=RUN_ID, token="secret")
        self.assertEqual(run["run_attempt"], ATTEMPT)
        self.assertEqual(len(jobs), 3)
        self.assertIn(f"/attempts/{ATTEMPT}/jobs?", get.call_args_list[1].args[0])
        self.assertNotIn("secret", get.call_args_list[1].args[0])

    def test_require_full_fails_on_scope_skip_but_not_normal_check(self):
        with tempfile.TemporaryDirectory() as folder:
            out1 = Path(folder) / "ordinary.json"
            out2 = Path(folder) / "release.json"
            with patch.object(evidence, "fetch", return_value=(workflow(), scoped())):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        evidence.main(["--repo", REPO, "--sha", SHA,
                                       "--run-id", str(RUN_ID), "--output", str(out1)]), 0)
                    self.assertEqual(
                        evidence.main(["--repo", REPO, "--sha", SHA,
                                       "--run-id", str(RUN_ID), "--output", str(out2),
                                       "--require-full"]), 1)
            self.assertFalse(json.loads(out1.read_text())["full_backend_64_shards_pass"])
            self.assertFalse(json.loads(out2.read_text())["full_backend_64_shards_pass"])

    def test_invalid_metadata_and_network_errors_fail_closed(self):
        with self.assertRaises(evidence.BackendEvidenceError):
            self.evaluate({"jobs": scoped()})
        with self.assertRaises(evidence.BackendEvidenceError):
            evidence.evaluate(run=workflow(), jobs=[], repo="bad/../repo",
                              sha=SHA, run_id=RUN_ID)
        from urllib.error import URLError
        with patch.object(evidence, "urlopen", side_effect=URLError("sensitive-data")):
            with self.assertRaises(evidence.BackendEvidenceError) as e:
                evidence.fetch(repo=REPO, sha=SHA, run_id=RUN_ID, token="secret-value")
            self.assertNotIn("sensitive-data", str(e.exception))
            self.assertNotIn("secret-value", str(e.exception))


if __name__ == "__main__":
    unittest.main()

"""Fail-closed, network-free regressions for Pilot exact-SHA CI metadata."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pilot_ci_evidence import (  # noqa: E402
    EvidenceError, REQUIRED, evaluate, fetch_runs, main,
)

REPO = "eh3aneba/maritime-claims-platform"
SHA = "a" * 40
OTHER_SHA = "b" * 40


def run(name: str, i: int, *, sha: str = SHA, attempt: int = 1,
        status: str = "completed", conclusion: str = "success") -> dict:
    return {
        "name": name, "id": i, "run_attempt": attempt,
        "status": status, "conclusion": conclusion,
        "head_sha": sha,
        "html_url": f"https://github.com/{REPO}/actions/runs/{i}",
    }


def complete_runs() -> list[dict]:
    return [run(name, 100 + idx) for idx, name in enumerate(REQUIRED.values())]


class CIReleaseEvidenceTests(unittest.TestCase):
    def test_exact_sha_all_six_pass_without_pilot_authorization(self):
        record = evaluate(complete_runs(), repo=REPO, sha=SHA)
        self.assertTrue(record["ci_gates_complete"])
        self.assertIs(record["pilot_authorized"], False)
        self.assertEqual(set(record["gates"]), set(REQUIRED))
        self.assertTrue(all(x["outcome"] == "pass" for x in record["gates"].values()))
        self.assertEqual(record["exact_head_sha"], SHA)

    def test_missing_wrong_head_and_skipped_cannot_pass(self):
        runs = complete_runs()
        runs[0] = run(runs[0]["name"], 100, sha=OTHER_SHA)
        runs[1]["conclusion"] = "skipped"
        record = evaluate(runs, repo=REPO, sha=SHA)
        self.assertFalse(record["ci_gates_complete"])
        self.assertEqual(record["gates"]["backend_exact_head"]["outcome"], "missing")
        self.assertEqual(record["gates"]["ci_exact_head"]["outcome"], "not_pass")

    def test_latest_run_override_and_rerun_attempt(self):
        runs = complete_runs()
        workflow = REQUIRED["backend_exact_head"]
        runs.extend([
            run(workflow, 999, conclusion="failure"),
            run(workflow, 999, attempt=2),
        ])
        record = evaluate(runs, repo=REPO, sha=SHA)
        self.assertTrue(record["ci_gates_complete"])
        self.assertEqual(record["gates"]["backend_exact_head"]["run_id"], 999)
        self.assertEqual(record["gates"]["backend_exact_head"]["run_attempt"], 2)
        runs.append(run(workflow, 1000, status="in_progress", conclusion=None))
        self.assertFalse(evaluate(runs, repo=REPO, sha=SHA)["ci_gates_complete"])

    def test_malformed_matching_run_fails_closed(self):
        runs = complete_runs()
        runs[0]["id"] = "100"
        with self.assertRaises(EvidenceError):
            evaluate(runs, repo=REPO, sha=SHA)
        runs = complete_runs()
        runs[0]["html_url"] = "https://attacker.invalid/claim"
        with self.assertRaises(EvidenceError):
            evaluate(runs, repo=REPO, sha=SHA)

    def test_invalid_repo_sha_and_response_fail_closed(self):
        for repo, sha in (("a/../b", SHA), (REPO, "deadbeef")):
            with self.assertRaises(EvidenceError):
                evaluate([], repo=repo, sha=sha)
        with self.assertRaises(EvidenceError):
            evaluate({"workflow_runs": []}, repo=REPO, sha=SHA)

    def test_new_output_is_exclusive_and_pending_does_not_pass(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ci.json"
            with patch("pilot_ci_evidence.fetch_runs", return_value=complete_runs()):
                self.assertEqual(
                    0, main(["--repo", REPO, "--sha", SHA, "--output", str(path)])
                )
            written = json.loads(path.read_text())
            self.assertTrue(written["ci_gates_complete"])
            self.assertIs(written["pilot_authorized"], False)
            with patch("pilot_ci_evidence.fetch_runs", return_value=[]):
                self.assertEqual(
                    2, main(["--repo", REPO, "--sha", SHA, "--output", str(path)])
                )
            self.assertEqual(written, json.loads(path.read_text()))
            other_path = Path(td) / "pending.json"
            with patch("pilot_ci_evidence.fetch_runs", return_value=[]):
                self.assertEqual(
                    1, main(["--repo", REPO, "--sha", SHA, "--output", str(other_path)])
                )
            self.assertFalse(json.loads(other_path.read_text())["ci_gates_complete"])

    def test_network_error_is_fail_closed_and_has_no_raw_exception(self):
        from urllib.error import URLError
        with patch("pilot_ci_evidence.urlopen", side_effect=URLError("raw-secret")):
            with self.assertRaisesRegex(EvidenceError, "could not be verified") as context:
                fetch_runs(repo=REPO, sha=SHA, token="secret-should-not-print")
            self.assertNotIn("raw-secret", str(context.exception))
            self.assertNotIn("secret-should-not-print", str(context.exception))


if __name__ == "__main__":
    unittest.main()

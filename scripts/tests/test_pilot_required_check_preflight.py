"""Offline no-network fail-closed regression for Protect main preactivation."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_required_check_preflight as proof  # noqa: E402

REPO = "eh3aneba/maritime-claims-platform"
SHA = "a" * 40
NUMBER = 999


def sample():
    pr = {
        "number": NUMBER,
        "state": "open",
        "head": {"sha": SHA, "repo": {"full_name": REPO}},
        "base": {"ref": "main", "repo": {"full_name": REPO}},
    }
    checks = [
        {
            "id": index + 1,
            "name": name,
            "head_sha": SHA,
            "status": "completed",
            "conclusion": "success",
            "app": {"slug": "github-actions"},
        }
        for index, name in enumerate(sorted(proof.EXPECTED_CONTEXTS))
    ]
    return pr, checks


class CheckNamesPreflightTests(unittest.TestCase):
    def evaluate(self, pr=None, checks=None):
        default_pr, default_checks = sample()
        return proof.evaluate(
            default_pr if pr is None else pr,
            default_checks if checks is None else checks,
            repo=REPO, pr_number=NUMBER, exact_sha=SHA,
        )

    def test_complete_exact_head_is_check_presence_only(self):
        record = self.evaluate()
        self.assertTrue(record["all_required_checks_green"])
        self.assertEqual(record["exact_name_contexts_present"], 11)
        self.assertFalse(record["ruleset_mutated"])
        self.assertFalse(record["failing_required_check_enforcement_proven"])
        self.assertFalse(record["pilot_authorized"])

    def test_missing_or_skipped_required_check_fails_without_hiding(self):
        pr, checks = sample()
        missing = checks[0]["name"]
        observed = self.evaluate(pr, checks[1:])
        self.assertFalse(observed["all_required_checks_green"])
        self.assertEqual(observed["expected_checks"][missing]["outcome"], "missing")
        checks[0]["conclusion"] = "skipped"
        observed = self.evaluate(pr, checks)
        self.assertFalse(observed["all_required_checks_green"])
        self.assertEqual(observed["expected_checks"][missing]["outcome"], "not_pass")

    def test_required_check_duplicate_is_ambiguous(self):
        pr, checks = sample()
        checks.append(deepcopy(checks[0]))
        result = self.evaluate(pr, checks)
        self.assertFalse(result["all_required_checks_green"])
        self.assertEqual(
            result["expected_checks"][checks[0]["name"]]["outcome"], "ambiguous"
        )

    def test_invalid_required_identity_raises(self):
        for key, value in (
            ("head_sha", "b" * 40),
            ("id", -1),
            ("app", {"slug": "untrusted-gate"}),
        ):
            pr, checks = sample()
            checks[0][key] = value
            with self.assertRaises(proof.GatePreflightError):
                self.evaluate(pr, checks)

    def test_foreign_or_mismatched_pr_fails(self):
        for path, value in (
            (("head", "sha"), "b" * 40),
            (("base", "ref"), "dev"),
            (("head", "repo"), {"full_name": "outside/repo"}),
        ):
            pr, checks = sample()
            node = pr
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = value
            with self.assertRaises(proof.GatePreflightError):
                self.evaluate(pr, checks)
        pr, checks = sample()
        pr["state"] = "closed"
        with self.assertRaises(proof.GatePreflightError):
            self.evaluate(pr, checks)

    def test_other_dynamic_jobs_do_not_substitute_missing_stable_gate(self):
        pr, checks = sample()
        checks = [x for x in checks if x["name"] != "PostgreSQL concurrency gate"]
        checks.append({
            "id": 200,
            "name": "PostgreSQL concurrency (scheduling)",
            "head_sha": SHA,
            "status": "completed",
            "conclusion": "success",
            "app": {"slug": "github-actions"},
        })
        result = self.evaluate(pr, checks)
        self.assertEqual(
            result["expected_checks"]["PostgreSQL concurrency gate"]["outcome"],
            "missing",
        )

    def test_unexpected_check_name_not_exposed(self):
        pr, checks = sample()
        checks.append({
            "id": 200,
            "name": "sensitive-customer-hostname.example",
            "head_sha": SHA,
            "status": "completed",
            "conclusion": "success",
            "app": {"slug": "github-actions"},
        })
        record = self.evaluate(pr, checks)
        self.assertNotIn("sensitive-customer-hostname", str(record))
        self.assertTrue(record["all_required_checks_green"])


    def test_101_check_runs_with_required_migration_on_page_two(self):
        """The exact #703 check list had 101 entries, including a page-2 gate."""
        from unittest.mock import patch
        pr, checks = sample()
        migration = next(x for x in checks if x["name"] == "PostgreSQL migration chain")
        first = [x for x in checks if x is not migration]
        first += [{"name": f"Backend tests shard {i}"} for i in range(90)]
        self.assertEqual(len(first), 100)
        called = []

        def request(url, *, token):
            called.append(url)
            if url.endswith(f"/pulls/{NUMBER}"):
                return pr
            if "page=1" in url:
                return {"total_count": 101, "check_runs": first}
            if "page=2" in url:
                return {"total_count": 101, "check_runs": [migration]}
            self.fail("unexpected API page")

        with patch.object(proof, "_request_json", side_effect=request):
            observed_pr, runs = proof.fetch(
                repo=REPO, pr_number=NUMBER, sha=SHA, token=None,
            )
        result = proof.evaluate(
            observed_pr, runs, repo=REPO, pr_number=NUMBER, exact_sha=SHA,
        )
        self.assertEqual(len(called), 3)
        self.assertEqual(len(runs), 101)
        self.assertEqual(result["exact_name_contexts_present"], 11)
        self.assertTrue(result["all_required_checks_green"])

    def test_truncated_second_page_rejected(self):
        from unittest.mock import patch
        pr, checks = sample()
        first = list(checks) + [{"name": f"optional-{i}"} for i in range(89)]
        self.assertEqual(len(first), 100)

        def request(url, *, token):
            if url.endswith(f"/pulls/{NUMBER}"):
                return pr
            if "page=1" in url:
                return {"total_count": 101, "check_runs": first}
            if "page=2" in url:
                return {"total_count": 101, "check_runs": []}
            self.fail("unexpected API page")

        with patch.object(proof, "_request_json", side_effect=request):
            with self.assertRaises(proof.GatePreflightError):
                proof.fetch(repo=REPO, pr_number=NUMBER, sha=SHA, token=None)

    def test_duplicate_required_context_hidden_on_second_page_fails_closed(self):
        from unittest.mock import patch
        pr, checks = sample()
        first = list(checks) + [{"name": f"optional-{i}"} for i in range(89)]
        dup = deepcopy(checks[0])
        dup["id"] = 100001

        def request(url, *, token):
            if url.endswith(f"/pulls/{NUMBER}"):
                return pr
            if "page=1" in url:
                return {"total_count": 101, "check_runs": first}
            if "page=2" in url:
                return {"total_count": 101, "check_runs": [dup]}
            self.fail("unexpected API page")

        with patch.object(proof, "_request_json", side_effect=request):
            observed_pr, runs = proof.fetch(
                repo=REPO, pr_number=NUMBER, sha=SHA, token=None,
            )
        result = proof.evaluate(
            observed_pr, runs, repo=REPO, pr_number=NUMBER, exact_sha=SHA,
        )
        self.assertFalse(result["all_required_checks_green"])
        self.assertEqual(
            result["expected_checks"][checks[0]["name"]]["outcome"], "ambiguous"
        )


if __name__ == "__main__":
    unittest.main()

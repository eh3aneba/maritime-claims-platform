"""Pure, network-free regressions for the Protect main metadata checker."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ruleset_evidence as proof  # noqa: E402

REPO = "eh3aneba/maritime-claims-platform"


def fixture(contexts=None):
    contexts = list(contexts if contexts is not None else sorted(proof.EXPECTED_CONTEXTS))
    listed = [{"id": 20842512, "name": "Protect main", "source": REPO,
               "source_type": "Repository"}]
    detail = {
        **listed[0], "enforcement": "active", "target": "branch",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "required_linear_history"},
            {"type": "pull_request", "parameters": {
                "allowed_merge_methods": ["squash"],
                "required_review_thread_resolution": True,
            }},
            {"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [{"context": x} for x in contexts],
            }},
        ]
    }
    return listed, detail


class ProtectMainEvidenceTests(unittest.TestCase):
    def test_complete_metadata_does_not_authorize_pilot_or_prove_fail_check(self):
        listed, detail = fixture()
        result = proof.evaluate(listed, detail, repo=REPO)
        self.assertTrue(result["metadata_complete"])
        self.assertIs(result["pilot_authorized"], False)
        self.assertIs(result["failing_check_enforcement_proven"], False)
        self.assertEqual(result["required_context_count"], 11)
        self.assertEqual(result["missing_expected_contexts"], [])

    def test_actual_four_required_contexts_fails_closed(self):
        present = ["Backend tests", "PostgreSQL migration chain",
                   "Frontend typecheck and build", "Docker Compose validation"]
        result = proof.evaluate(*fixture(present), repo=REPO)
        self.assertFalse(result["metadata_complete"])
        self.assertEqual(len(result["missing_expected_contexts"]), 7)
        self.assertIn("PostgreSQL concurrency gate", result["missing_expected_contexts"])

    def test_no_bypass_and_strict_policy_are_mandatory(self):
        for mutate in (
            lambda d: d.update(bypass_actors=[{"actor_id": 1}]),
            lambda d: d.update(enforcement="evaluate"),
            lambda d: d["rules"][-1]["parameters"].update(
                strict_required_status_checks_policy=False),
            lambda d: d["rules"][-2]["parameters"].update(
                allowed_merge_methods=["squash", "merge"]),
            lambda d: d["rules"][-2]["parameters"].update(
                required_review_thread_resolution=False),
            lambda d: d["conditions"]["ref_name"].update(include=["refs/heads/main"]),
            lambda d: d["rules"].pop(0),
        ):
            listed, detail = fixture()
            mutate(detail)
            self.assertFalse(proof.evaluate(listed, detail, repo=REPO)["metadata_complete"])

    def test_duplicates_unexpected_and_malformed_are_not_pass(self):
        listed, detail = fixture()
        extra = deepcopy(detail)
        extra["rules"][-1]["parameters"]["required_status_checks"].append(
            {"context": "unexpected-sensitive-context"})
        result = proof.evaluate(listed, extra, repo=REPO)
        self.assertFalse(result["metadata_complete"])
        self.assertEqual(result["unexpected_context_count"], 1)
        self.assertNotIn("unexpected-sensitive-context", json.dumps(result))
        for bad in (
            None,
            {**detail, "rules": "fake"},
            {**detail, "id": 123},
            {**detail, "bypass_actors": None},
        ):
            with self.assertRaises(proof.EvidenceError):
                proof.evaluate(listed, bad, repo=REPO)

    def test_records_created_exclusively_without_mutating_protection(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "readback.json"
            with patch.object(proof, "fetch", return_value=fixture()):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(proof.main(["--repo", REPO, "--output",
                                                 str(out)]), 0)
            data = json.loads(out.read_text())
            self.assertTrue(data["metadata_complete"])
            self.assertFalse(data["pilot_authorized"])
            with patch.object(proof, "fetch", return_value=fixture()):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(proof.main(["--repo", REPO, "--output",
                                                 str(out)]), 2)

    def test_api_failure_never_prints_raw_exception(self):
        with patch.object(proof, "urlopen",
                          side_effect=OSError("secret-bearing-request-url")):
            with self.assertRaisesRegex(proof.EvidenceError,
                                        "ruleset readback unavailable") as ctx:
                proof._read_json("https://api.github.com/repos/test", token="secret")
            self.assertNotIn("secret", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

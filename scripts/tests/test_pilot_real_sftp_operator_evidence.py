"""Offline tests: bounded real-provider acceptance evidence never authorizes GO."""
from __future__ import annotations

from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_real_sftp_operator_evidence as proof  # noqa: E402

SHA = "a" * 40


def complete():
    result = proof.draft(SHA)
    result["operator_role"] = "sftp_primary_operator"
    result["independent_reviewer_role"] = "sftp_release_reviewer"
    result["observed_at_utc"] = "2026-10-12T06:00:00Z"
    result["references"] = {
        x: "artifact://test-only-sftp-evidence"
        for x in proof.METADATA_REFS
    }
    for name in proof.POSITIVE:
        result["positive"][name] = {
            "outcome": "pass",
            "real_server_proof_ref": "artifact://test-only-positive-case",
        }
    for name in proof.NEGATIVE:
        result["negative"][name] = {
            "outcome": "pass",
            "real_server_proof_ref": "artifact://test-only-negative-case",
            "unreproducible_limitation_ref": "",
            "deterministic_ci_fallback_ref": "",
        }
    return result


class RealSftpOperatorEvidenceTests(unittest.TestCase):
    def test_draft_is_all_pending_and_never_go(self):
        draft = proof.draft(SHA)
        self.assertEqual(len(draft["positive"]), 16)
        self.assertEqual(len(draft["negative"]), 10)
        self.assertTrue(all(x["outcome"] == "pending" for x in draft["positive"].values()))
        with self.assertRaises(proof.OperatorEvidenceError):
            proof.check(draft, sha=SHA)

    def test_complete_is_only_structural_not_approval(self):
        record = proof.check(complete(), sha=SHA)
        self.assertTrue(record["record_refs_structurally_complete"])
        self.assertEqual(record["positive_real_server_proofs"], 16)
        self.assertEqual(record["negative_real_server_proofs"], 10)
        for x in ("actual_server_exercise_independently_verified",
                  "credentials_and_data_compliance_independently_verified",
                  "pilot_sftp_go_authorized", "pilot_authorized"):
            self.assertIs(record[x], False)

    def test_missing_or_fake_positive_case_fails(self):
        for operation in (
            lambda d: d["positive"].pop("canonical_initial_v1_admission"),
            lambda d: d["positive"]["canonical_initial_v1_admission"].update(
                outcome="skipped"),
            lambda d: d["positive"]["next_due_tick_unchanged"].update(
                real_server_proof_ref=""),
        ):
            data = complete()
            operation(data)
            with self.assertRaises(proof.OperatorEvidenceError):
                proof.check(data, sha=SHA)

    def test_unreproducible_negative_requires_both_independent_refs(self):
        record = complete()
        case = record["negative"]["unsupported_weak_negotiation"]
        case.update(outcome="unreproducible", real_server_proof_ref="",
                    unreproducible_limitation_ref="ticket://sftp-operator-limit",
                    deterministic_ci_fallback_ref="artifact://ci-negative-case")
        result = proof.check(record, sha=SHA)
        self.assertEqual(result["negative_with_deterministic_fallback"], 1)
        self.assertEqual(result["negative_real_server_proofs"], 9)
        self.assertFalse(result["pilot_sftp_go_authorized"])
        for omitted in ("unreproducible_limitation_ref",
                        "deterministic_ci_fallback_ref"):
            bad = deepcopy(record)
            bad["negative"]["unsupported_weak_negotiation"][omitted] = ""
            with self.assertRaises(proof.OperatorEvidenceError):
                proof.check(bad, sha=SHA)

    def test_no_customer_data_mutations_or_fake_go(self):
        for field in ("customer_credentials_used", "customer_files_used",
                      "remote_mutation_authorized", "real_provider_go_authorized"):
            result = complete()
            result[field] = True
            with self.assertRaises(proof.OperatorEvidenceError):
                proof.check(result, sha=SHA)
        for field in proof.METADATA_REFS:
            result = complete()
            result["references"][field] = "private://some-host/path"
            with self.assertRaises(proof.OperatorEvidenceError):
                proof.check(result, sha=SHA)

    def test_identity_timestamp_roles_and_keys_fail_closed(self):
        for mutation in (
            lambda d: d.update(candidate_release_sha="b" * 40),
            lambda d: d.update(observed_at_utc="2026-10-12T06:00:00+04:00"),
            lambda d: d.update(independent_reviewer_role=d["operator_role"]),
            lambda d: d["negative"].pop("wrong_host_key_pin"),
            lambda d: d.update(unexpected="not allowed"),
        ):
            record = complete()
            mutation(record)
            with self.assertRaises(proof.OperatorEvidenceError):
                proof.check(record, sha=SHA)

    def test_exclusive_cli_artifacts_and_sanitized_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started = root / "draft.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(proof.main(["init", "--sha", SHA,
                                            "--output", str(started)]), 0)
            self.assertEqual(proof.main(["init", "--sha", SHA,
                                         "--output", str(started)]), 2)
            result = root / "verified.json"
            started.write_text(json.dumps(complete()))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(proof.main(["check", str(started),
                                             "--sha", SHA,
                                             "--output", str(result)]), 0)
            data = json.loads(result.read_text())
            self.assertFalse(data["pilot_authorized"])
            self.assertEqual(proof.main(["check", str(started), "--sha", SHA,
                                         "--output", str(result)]), 2)


if __name__ == "__main__":
    unittest.main()

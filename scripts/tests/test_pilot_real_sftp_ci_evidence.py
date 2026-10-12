"""Offline, no-network tests for the SFTP CI outcome evidence record."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_real_sftp_ci_evidence as proof  # noqa: E402

SHA = "a" * 40


def good():
    return {key: "success" for key in proof.STEP_KEYS}


class SftpOutcomeEvidenceTests(unittest.TestCase):
    def _record(self, **changes):
        args = dict(
            expected_sha=SHA, checked_out_sha=SHA,
            run_id="400", run_attempt="2",
            server_version="1:9.7p1-7ubuntu4",
            outcomes=good(),
        )
        args.update(changes)
        return proof.build_record(**args)

    def test_complete_outcomes_never_assert_operational_go(self):
        record = self._record()
        self.assertTrue(record["all_six_ci_steps_passed"])
        self.assertEqual(record["ci_result"], "six_ci_steps_pass")
        self.assertEqual(record["candidate_commit_sha"], SHA)
        self.assertEqual(record["tested_checkout_sha"], SHA)
        self.assertFalse(record["pilot_go"])
        self.assertFalse(record["customer_data_authorized"])
        self.assertFalse(record["production_scanner_and_store_proof"])
        self.assertEqual(set(record["ci_step_outcomes"]), set(proof.STEP_KEYS))

    def test_failure_cancel_skip_missing_and_unknown_never_pass(self):
        for bad in ("failure", "cancelled", "skipped", "", "nonsense"):
            outcomes = good()
            outcomes["initial_custody"] = bad
            record = self._record(outcomes=outcomes)
            self.assertFalse(record["all_six_ci_steps_passed"])
            self.assertEqual(record["ci_result"], "incomplete_or_failed")
            self.assertEqual(record["ci_step_outcomes"]["initial_custody"],
                             bad if bad in proof.VALID_OUTCOMES else "not_reported")

    def test_unknown_keys_and_mismatched_checkout_fail_closed(self):
        with self.assertRaises(proof.RecordError):
            self._record(checked_out_sha="b" * 40)
        with self.assertRaises(proof.RecordError):
            self._record(outcomes={"postgres_schema": "success"})
        with self.assertRaises(proof.RecordError):
            self._record(run_attempt="0")
        with self.assertRaises(proof.RecordError):
            self._record(run_id="-1")
        with self.assertRaises(proof.RecordError):
            self._record(expected_sha="not-a-git-sha")

    def test_does_not_copy_untrusted_server_version(self):
        secret = "private-key-secret"
        record = self._record(server_version=secret + " invalid raw text")
        self.assertEqual(record["observed_openssh_package_version"], "not_observed")
        self.assertNotIn(secret, json.dumps(record))

    def test_cli_record_exclusive_and_failed_step_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "summary.json"
            with patch.dict("os.environ", {
                "MCRI_SFTP_STEP_" + key.upper(): ("failure" if key == "live_runtime" else "success")
                for key in proof.STEP_KEYS
            }):
                argv = [
                    "--output", str(output), "--candidate-sha", SHA,
                    "--checked-out-sha", SHA, "--run-id", "4",
                    "--run-attempt", "1", "--server-version", "openssh9",
                ]
                self.assertEqual(proof.main(argv), 0)
                rec = json.loads(output.read_text())
                self.assertFalse(rec["all_six_ci_steps_passed"])
                self.assertEqual(rec["ci_step_outcomes"]["live_runtime"], "failure")
                self.assertEqual(proof.main(argv), 2)


if __name__ == "__main__":
    unittest.main()

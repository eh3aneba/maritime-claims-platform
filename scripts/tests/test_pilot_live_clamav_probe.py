"""Network-free fail-closed checks for synthetic real-ClamAV acceptance."""
from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_live_clamav_probe as probe  # noqa: E402

SHA = "a" * 40
PASS = json.dumps({
    "schema": "mcri-ci-clamav-test-v1",
    "ping": "pass", "clean": "pass", "eicar_detected": "pass",
})


class LiveClamavProbeTests(unittest.TestCase):
    def test_complete_synthetic_proof_cannot_authorize_pilot(self):
        result = probe.evaluate(PASS, returncode=0, release_sha=SHA)
        self.assertTrue(result["scanner_runtime_behavior_observed"])
        for key in ("production_scanner_attested", "customer_evidence_verified",
                    "operator_approved", "pilot_authorized"):
            self.assertIs(result[key], False)
        self.assertNotIn("EICAR-STANDARD", json.dumps(result))
        self.assertEqual(result["environment"], "synthetic_ci_only")

    def test_fail_closed_on_malformed_result_status_and_sha(self):
        cases = (
            (PASS, 1, SHA),
            (PASS, 0, "wrong"),
            ("", 0, SHA),
            ('{"schema":"mcri-ci-clamav-test-v1","result":"fail"}', 0, SHA),
            (PASS.replace('"eicar_detected": "pass"', '"eicar_detected": "skip"'), 0, SHA),
            (PASS + "\nraw secret", 0, SHA),
        )
        for raw, code, sha in cases:
            with self.assertRaises(probe.ProbeError):
                probe.evaluate(raw, returncode=code, release_sha=sha)

    def test_docker_exec_is_bounded_stdin_only_no_raw_output(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="fixture: confidential-body",
            stderr="password: secret-value",
        )
        with patch.object(probe.subprocess, "run", return_value=completed) as mock_run:
            stdout, code = probe.observe(env_file=".env.performance")
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "fixture: confidential-body")
        call = mock_run.call_args
        self.assertEqual(call.args[0], [
            "docker", "compose", "--env-file", ".env.performance",
            "exec", "-T", "api", "python", "-",
        ])
        self.assertEqual(call.kwargs["input"], probe._IN_CONTAINER)
        self.assertTrue(call.kwargs["capture_output"])
        self.assertLessEqual(call.kwargs["timeout"], 90)
        with self.assertRaises(probe.ProbeError) as ctx:
            probe.evaluate(stdout, returncode=code, release_sha=SHA)
        self.assertNotIn("confidential-body", str(ctx.exception))
        self.assertNotIn("secret-value", str(ctx.exception))

    def test_program_guards_test_environment_and_no_claim_data(self):
        program = probe._IN_CONTAINER
        self.assertIn('os.environ.get("APP_ENV") != "test"', program)
        self.assertIn('os.environ.get("MALWARE_SCAN_ENABLED", "")', program)
        self.assertIn("ping_clamd(", program)
        self.assertIn("scan_file(", program)
        self.assertIn("TemporaryDirectory(", program)
        self.assertIn("MalwareScanVerdict.CLEAN", program)
        self.assertIn("MalwareScanVerdict.INFECTED", program)
        self.assertNotIn("Claim(", program)
        self.assertNotIn("postgres", program.lower())

    def test_output_is_exclusive_and_failed_or_missing_never_accepted(self):
        with tempfile.TemporaryDirectory() as dirname:
            out = Path(dirname) / "synthetic-clamav.json"
            argv = ["--env-file", ".env.performance", "--release-sha", SHA,
                    "--output", str(out)]
            with patch.object(probe, "observe", return_value=(PASS, 0)):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(probe.main(argv), 0)
            document = json.loads(out.read_text())
            self.assertFalse(document["pilot_authorized"])
            with patch.object(probe, "observe", return_value=(PASS, 0)):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(probe.main(argv), 2)
            failed_output = Path(dirname) / "no-go.json"
            argv[-1] = str(failed_output)
            with patch.object(probe, "observe", return_value=("", 1)):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(probe.main(argv), 2)
            self.assertFalse(failed_output.exists())


if __name__ == "__main__":
    unittest.main()

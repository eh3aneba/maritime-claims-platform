"""Network-free CI synthetic post-recovery resume gate regressions."""
from pathlib import Path
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ci_resume_probe as p  # noqa: E402

SHA = "a" * 40
ENV = {
    "APP_ENV": "test",
    "MCRI_CI_RESUME_PROBE": "1",
    "POSTGRES_DB": "mcri_performance",
    "POSTGRES_USER": "mcri_performance",
    "MCRI_DEMO_PASSWORD": "".join(("synthetic", "-", "ci", "-", "placeholder", "-", "only")),
}


class ResumeProbeTests(unittest.TestCase):
    def test_prod_or_wrong_ci_identity_never_restarts(self):
        cases = [
            (".env", ENV),
            (".env.performance", {**ENV, "APP_ENV": "production"}),
            (".env.performance", {**ENV, "MCRI_CI_RESUME_PROBE": "0"}),
            (".env.performance", {**ENV, "POSTGRES_DB": "real-database"}),
            (".env.performance", {**ENV, "POSTGRES_USER": "real-user"}),
            (".env.performance", {**ENV, "MCRI_DEMO_PASSWORD": ""}),
        ]
        for env_file, env in cases:
            with patch.object(p, "_run") as command, self.assertRaises(p.ResumeError):
                p.observe(env_file=env_file, env=env, release_sha=SHA)
            command.assert_not_called()
        with self.assertRaises(p.ResumeError):
            p.validate_guard(env_file=".env.performance", env=ENV, release_sha="bad")

    def test_healthy_resume_uses_exact_service_list_and_privacy_safe_output(self):
        commands = []
        def command(cmd, *, timeout=90):
            commands.append(cmd)
            if cmd[-4:] == ["ps", "--status", "running", "--services"]:
                return "db\nclamav"
            return ""
        with patch.object(p, "_run", side_effect=command), \
             patch.object(p.readiness, "observe", return_value=[]), \
             patch.object(p.readiness, "evaluate",
                          return_value={"compose_status_complete": True}), \
             patch.object(p, "_get_health", return_value=True), \
             patch.object(p, "_authenticated_claim_read", return_value=True):
            result = p.observe(env_file=".env.performance", env=ENV,
                               release_sha=SHA)
        self.assertEqual(commands[0], p._compose(
            ".env.performance", "ps", "--status", "running", "--services"))
        self.assertEqual(commands[1], p._compose(
            ".env.performance", "start", *p.RESTART_SERVICES))
        self.assertEqual(result["writers_started"], 7)
        self.assertTrue(result["synthetic_authenticated_claim_read_after_restart"])
        for key in ("pilot_authorized", "fresh_host_restore_verified",
                    "rollback_to_previous_release_verified",
                    "independent_operator_approved", "real_customer_evidence_verified"):
            self.assertFalse(result[key])
        self.assertNotIn(ENV["MCRI_DEMO_PASSWORD"], json.dumps(result))
        self.assertNotIn("manager@demo.mcri.app", json.dumps(result))

    def test_unexpected_running_writer_blocks_before_restart(self):
        for status in ("db\nclamav\nworker", "db", "db\nclamav\nclamav", ""):
            with patch.object(p, "_run", return_value=status) as run:
                with self.assertRaises(p.ResumeError):
                    p.observe(env_file=".env.performance", env=ENV,
                              release_sha=SHA)
                run.assert_called_once()

    def test_unhealthy_stack_fails_without_authentication(self):
        def command(cmd, *, timeout=90):
            return "db\nclamav" if "ps" in cmd else ""
        with patch.object(p, "_run", side_effect=command), \
             patch.object(p.readiness, "observe", return_value=[]), \
             patch.object(p.readiness, "evaluate",
                          return_value={"compose_status_complete": False}), \
             patch.object(p, "_authenticated_claim_read") as auth, \
             patch.object(p.time, "sleep"), \
             self.assertRaisesRegex(p.ResumeError, "not healthy"):
            p.observe(env_file=".env.performance", env=ENV,
                      release_sha=SHA, max_attempts=2)
        auth.assert_not_called()

    def test_successful_compose_without_http_ready_is_not_success(self):
        with patch.object(p, "_run", side_effect=["db\nclamav", ""]), \
             patch.object(p.readiness, "observe", return_value=[]), \
             patch.object(p.readiness, "evaluate",
                          return_value={"compose_status_complete": True}), \
             patch.object(p, "_get_health", return_value=False), \
             patch.object(p, "_authenticated_claim_read") as auth, \
             self.assertRaises(p.ResumeError):
            p.observe(env_file=".env.performance", env=ENV,
                      release_sha=SHA, max_attempts=1)
        auth.assert_not_called()

    def test_authentication_or_claim_failure_blocks_success(self):
        with patch.object(p, "_run", side_effect=["db\nclamav", ""]), \
             patch.object(p.readiness, "observe", return_value=[]), \
             patch.object(p.readiness, "evaluate",
                          return_value={"compose_status_complete": True}), \
             patch.object(p, "_get_health", return_value=True), \
             patch.object(p, "_authenticated_claim_read", return_value=False), \
             self.assertRaisesRegex(p.ResumeError, "authenticated claim read"):
            p.observe(env_file=".env.performance", env=ENV,
                      release_sha=SHA, max_attempts=1)

    def test_compose_error_does_not_expose_private_output(self):
        result = subprocess.CompletedProcess(
            ["docker"], 1, stdout="synthetic-customer-document",
            stderr="secret-environment-variable")
        with patch.object(p.subprocess, "run", return_value=result), \
             self.assertRaises(p.ResumeError) as e:
            p._run(["docker", "compose"])
        self.assertNotIn("secret-environment-variable", str(e.exception))
        self.assertNotIn("synthetic-customer-document", str(e.exception))

    def test_exclusive_output_fails_closed_outside_ci(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "result.json"
            with patch.dict(p.os.environ, {"APP_ENV": "production"}, clear=True), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(p.main([
                    "--env-file", ".env.performance", "--release-sha", SHA,
                    "--output", str(out)]), 2)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()

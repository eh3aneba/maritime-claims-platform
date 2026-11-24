"""No-network regression tests for limited first-manual CI fault injection."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ci_first_manual_fault_probe as p


SHA = "a" * 40


class FirstManualFaultProbeTests(unittest.TestCase):
    def test_outside_hosted_synthetic_scope_never_touches_docker(self):
        for field in ("APP_ENV", "GITHUB_ACTIONS", "RUNNER_ENVIRONMENT",
                      "MCRI_CI_FIRST_MANUAL_FAULT_PROBE", "DOCKER_HOST"):
            with self.subTest(field=field):
                env = {"MCRI_CI_FIRST_MANUAL_FAULT_PROBE": "1"}
                with patch.object(p, "admitted_source", return_value=False), \
                     patch.object(p, "run") as runner:
                    with self.assertRaises(p.FaultProbeError):
                        p.validate_scope(env)
                    runner.assert_not_called()

    def test_detects_target_outage_but_rejects_unrelated_failed_service(self):
        rows = {s: {"observed": True, "status": "running", "pass": True}
                for s in ("api", "worker", "db")}
        rows["api"] = {"observed": True, "status": "exited", "pass": False}
        with patch.object(p, "status", return_value=([], {
            "compose_status_complete": False, "services": rows,
        })), patch.object(p, "http_ready", return_value=False):
            p.detect("api", SHA)
        with patch.object(p, "status", return_value=([], {
            "compose_status_complete": False,
            "services": {**rows, "worker": {"observed": True, "status": "exited", "pass": False}},
        })), patch.object(p, "http_ready", return_value=False):
            with self.assertRaises(p.FaultProbeError):
                p.detect("api", SHA)

    def test_health_endpoint_must_go_unready_during_api_outage(self):
        rows = {s: {"observed": True, "status": "running", "pass": True}
                for s in ("api", "worker")}
        rows["api"] = {"observed": True, "status": "exited", "pass": False}
        with patch.object(p, "status", return_value=([], {
            "compose_status_complete": False, "services": rows,
        })), patch.object(p, "http_ready", return_value=True):
            with self.assertRaises(p.FaultProbeError):
                p.detect("api", SHA)

    def test_success_stops_and_restarts_only_allowed_service(self):
        with patch.object(p, "compose") as command, \
             patch.object(p, "detect") as detection, \
             patch.object(p, "recover") as recovery:
            p.exercise_once("api", SHA)
            self.assertEqual(command.call_args.args, ("stop", "api"))
            detection.assert_called_once_with("api", SHA)
            recovery.assert_called_once_with("api", SHA)
        with patch.object(p, "compose") as command:
            with self.assertRaises(p.FaultProbeError):
                p.exercise_once("db", SHA)
            command.assert_not_called()

    def test_failure_attempts_recovery_without_reporting_success(self):
        with patch.object(p, "compose") as command, \
             patch.object(p, "detect", side_effect=p.FaultProbeError("missing")):
            with self.assertRaises(p.FaultProbeError):
                p.exercise_once("worker", SHA)
            self.assertEqual([c.args for c in command.call_args_list],
                             [("stop", "worker"), ("start", "worker")])

    def test_scope_requires_prior_rollback_proof_and_no_operator_claim(self):
        with patch.object(p, "admitted_source", return_value=True), \
             patch.object(p, "run", return_value=SHA), \
             patch.object(p, "PRIOR_PROOF") as proof:
            proof.is_file.return_value = False
            with self.assertRaises(p.FaultProbeError):
                p.validate_scope({"MCRI_CI_FIRST_MANUAL_FAULT_PROBE": "1"})


if __name__ == "__main__":
    unittest.main()

"""Network-free tests for read-only Pilot Compose status observation."""
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
import pilot_compose_readiness as probe  # noqa: E402

SHA = "a" * 40


def good_containers():
    items = []
    for service in probe.EXPECTED:
        if service in probe.HEALTHY:
            items.append({"Service": service, "State": "running",
                          "Health": "healthy", "ExitCode": 0,
                          "Image": "dont-record/image@sha256:" + "e" * 64,
                          "Name": "secret-customer-container-name"})
        elif service in probe.ONESHOT:
            items.append({"Service": service, "State": "exited",
                          "ExitCode": 0, "Health": ""})
        else:
            items.append({"Service": service, "State": "running",
                          "Health": "", "ExitCode": 0})
    return items


class PilotComposeReadinessTests(unittest.TestCase):
    def test_all_expected_states_observed_but_not_pilot_authorization(self):
        result = probe.evaluate(good_containers(), release_sha=SHA)
        self.assertTrue(result["compose_status_complete"])
        self.assertEqual(result["service_count_passing"], 11)
        for key in ("image_digest_verified", "deployed_release_identity_verified",
                    "fresh_host_verified", "independent_operator_verified",
                    "pilot_authorized"):
            self.assertIs(result[key], False)
        serialized = json.dumps(result)
        self.assertNotIn("secret-customer-container-name", serialized)
        self.assertNotIn("dont-record", serialized)

    def test_absent_unhealthy_failed_and_unknown_services_fail_closed(self):
        baseline = good_containers()
        for variant in (
            baseline[:-1],
            [{**x, "Health": "unhealthy"} if x["Service"] == "clamav" else x
             for x in baseline],
            [{**x, "State": "exited", "ExitCode": 1}
             if x["Service"] == "migrate" else x for x in baseline],
            [{**x, "State": "restarting"}
             if x["Service"] == "worker" else x for x in baseline],
            [{**x, "Health": "starting"}
             if x["Service"] == "worker" else x for x in baseline],
            [*baseline, {"Service": "unknown-secret-worker", "State": "running"}],
            [*baseline, baseline[0]],
            [*baseline, {"Service": "demo-seed", "State": "running"}],
        ):
            result = probe.evaluate(variant, release_sha=SHA)
            self.assertFalse(result["compose_status_complete"])
            self.assertNotIn("unknown-secret-worker", json.dumps(result))
        self.assertTrue(probe.evaluate(
            [*baseline, {"Service": "demo-seed", "State": "exited", "ExitCode": 0}],
            release_sha=SHA)["compose_status_complete"])

    def test_malformed_input_or_sha_never_passes(self):
        with self.assertRaises(probe.ReadinessError):
            probe.evaluate(good_containers(), release_sha="deadbeef")
        for body in ("", "{bad", '"string"', "1", "{}\n{bad"):
            with self.assertRaises(probe.ReadinessError):
                probe.parse_ps(body)
        with self.assertRaises(probe.ReadinessError):
            probe.evaluate([{"Service": None}], release_sha=SHA)

    def test_json_array_and_json_lines(self):
        arr = good_containers()
        self.assertEqual(probe.parse_ps(json.dumps(arr)), arr)
        self.assertEqual(probe.parse_ps("\n".join(json.dumps(x) for x in arr)), arr)

    def test_observe_uses_read_only_compose_ps_without_raw_stderr(self):
        good = good_containers()
        returned = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(good),
            stderr="secret-environment-value")
        with patch.object(probe.subprocess, "run", return_value=returned) as run:
            self.assertEqual(probe.observe(env_file=".env"), good)
        self.assertEqual(run.call_args.args[0], [
            "docker", "compose", "--env-file", ".env", "ps", "--all",
            "--format", "json",
        ])
        with patch.object(probe.subprocess, "run", return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="password: leaked-synthetic")
        ):
            with self.assertRaises(probe.ReadinessError) as ctx:
                probe.observe(env_file=".env")
            self.assertNotIn("leaked-synthetic", str(ctx.exception))

    def test_new_output_is_exclusive_and_incomplete_is_no_go(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "pilot-status.json"
            argv = ["--env-file", ".env", "--release-sha", SHA,
                    "--output", str(output)]
            with patch.object(probe, "observe", return_value=good_containers()):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(probe.main(argv), 0)
            record = json.loads(output.read_text())
            self.assertFalse(record["pilot_authorized"])
            with patch.object(probe, "observe", return_value=good_containers()):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(probe.main(argv), 2)
            incomplete = Path(d) / "incomplete.json"
            argv[-1] = str(incomplete)
            with patch.object(probe, "observe", return_value=good_containers()[:-1]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(probe.main(argv), 1)
            self.assertFalse(json.loads(incomplete.read_text())["compose_status_complete"])


if __name__ == "__main__":
    unittest.main()

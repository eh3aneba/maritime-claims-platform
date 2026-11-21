"""Regression tests: never leak rendered Compose secrets or claim runtime proof."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.pilot_compose_readiness import EXPECTED
from scripts.pilot_rc_compose_feature_observation import (
    COMPOSE, ComposeScopeError, PILOT_APP_ENV_SERVICES, inspect_config, main, observe_config,
)

SHA = "a" * 40


def safe_compose() -> dict:
    services = {name: {"environment": {}} for name in EXPECTED}
    for name in ("api", "worker", "preflight"):
        services[name]["environment"].update({
            "AI_PROVIDER": "disabled",
            "AI_MODEL": "",
            "OPENAI_API_KEY": "",
            "ALLOW_EXTERNAL_AI_RESTRICTED": "false",
            "DATABASE_URL": "postgres://private-user:private-secret@db:5432/private",
        })
    services["worker"]["environment"].update({
        "OCR_ENABLED": "true",
        "OCR_LANGUAGES": "eng+fas",
    })
    services["demo-seed"] = {"environment": {"AI_PROVIDER": "disabled"}}
    return {"services": services}


class PilotRCComposeFeatureObservationTests(unittest.TestCase):
    def test_documented_direct_file_and_package_cli_load_without_pythonpath(self):
        root = Path(__file__).resolve().parents[2]
        entry = root / "scripts" / "pilot_rc_compose_feature_observation.py"
        # Direct-file execution resolves sys.path[0] to scripts/, NOT the
        # repository root. Both documented operator and module forms must work.
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        for command in (
            [sys.executable, str(entry), "--help"],
            [sys.executable, "-m", "scripts.pilot_rc_compose_feature_observation", "--help"],
        ):
            with self.subTest(command=command[1:]):
                result = subprocess.run(
                    command, cwd=root, env=environment,
                    capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(0, result.returncode, msg=result.stderr[:500])
                self.assertIn("--release-sha", result.stdout)
                self.assertNotIn("Traceback", result.stderr)

    def test_safe_synthetic_config_does_not_claim_running_acceptance(self):
        result = inspect_config(safe_compose(), release_sha=SHA)
        self.assertTrue(result["compose_ai_and_adapter_config_safe"])
        self.assertEqual([], result["check_failures"])
        for key in (
            "runtime_environment_attested",
            "effective_database_connector_state_attested",
            "network_egress_isolation_attested",
            "persian_critical_ocr_semantics_attested",
            "persian_critical_extraction_disabled_attested",
            "real_customer_data_authorized",
            "pilot_accepted",
        ):
            self.assertIs(result[key], False)
        self.assertNotIn("private-secret", json.dumps(result))

    def test_first_manual_pilot_requires_consistent_startup_scope_and_ocr_off(self):
        configuration = safe_compose()
        for service in PILOT_APP_ENV_SERVICES | {"demo-seed"}:
            configuration["services"][service]["environment"]["APP_ENV"] = "pilot"
        configuration["services"]["preflight"]["environment"]["OCR_ENABLED"] = "false"
        configuration["services"]["worker"]["environment"]["OCR_ENABLED"] = "false"
        clean = inspect_config(configuration, release_sha=SHA)
        self.assertTrue(clean["compose_ai_and_adapter_config_safe"])
        self.assertFalse(clean["persian_critical_extraction_disabled_attested"])

        for service, flag, value, expected in (
            ("worker", "OCR_ENABLED", "true", "manual_pilot_ocr_not_disabled"),
            ("preflight", "OCR_ENABLED", "true", "manual_pilot_ocr_not_disabled"),
            ("api", "APP_ENV", "test", "manual_pilot_environment_mismatch"),
        ):
            with self.subTest(service=service, flag=flag):
                case = safe_compose()
                for name in PILOT_APP_ENV_SERVICES | {"demo-seed"}:
                    case["services"][name]["environment"]["APP_ENV"] = "pilot"
                case["services"]["preflight"]["environment"]["OCR_ENABLED"] = "false"
                case["services"]["worker"]["environment"]["OCR_ENABLED"] = "false"
                case["services"][service]["environment"][flag] = value
                got = inspect_config(case, release_sha=SHA)
                self.assertFalse(got["compose_ai_and_adapter_config_safe"])
                self.assertIn(expected, got["check_failures"])
                self.assertFalse(got["pilot_accepted"])

    def test_manual_pilot_rejects_partial_db_worker_and_demo_scope(self):
        configuration = safe_compose()
        for service in PILOT_APP_ENV_SERVICES | {"demo-seed"}:
            configuration["services"][service]["environment"]["APP_ENV"] = "pilot"
        for service in ("worker", "preflight"):
            configuration["services"][service]["environment"]["OCR_ENABLED"] = "false"
        self.assertTrue(inspect_config(configuration, release_sha=SHA)[
            "compose_ai_and_adapter_config_safe"
        ])

        # All DB-connected workers are live in the same Compose project;
        # a mixed env allows one of them to use a different adapter policy.
        for service in PILOT_APP_ENV_SERVICES | {"demo-seed"}:
            for mode in ("test", None):
                with self.subTest(service=service, mode=mode):
                    candidate = json.loads(json.dumps(configuration))
                    env = candidate["services"][service]["environment"]
                    if mode is None:
                        env.pop("APP_ENV")
                    else:
                        env["APP_ENV"] = mode
                    record = inspect_config(candidate, release_sha=SHA)
                    self.assertFalse(record["compose_ai_and_adapter_config_safe"])
                    self.assertIn("manual_pilot_environment_mismatch",
                                  record["check_failures"])
                    self.assertFalse(record["pilot_accepted"])
                    self.assertNotIn("private-secret", json.dumps(record))

    def test_isolated_database_worker_pilot_setting_activates_strict_scope(self):
        # With only one side worker switched to pilot, the observer must not
        # treat the remaining test/development app services as a safe pilot.
        for name in PILOT_APP_ENV_SERVICES | {"demo-seed"}:
            with self.subTest(service=name):
                candidate = safe_compose()
                candidate["services"][name]["environment"]["APP_ENV"] = "pilot"
                record = inspect_config(candidate, release_sha=SHA)
                self.assertFalse(record["compose_ai_and_adapter_config_safe"])
                self.assertIn("manual_pilot_environment_mismatch",
                              record["check_failures"])
                self.assertFalse(record["pilot_accepted"])

    def test_local_and_external_ai_paths_fail_closed(self):
        for name, key, value in (
            ("api", "AI_PROVIDER", "openai"),
            ("worker", "AI_PROVIDER", "ollama_local"),
            ("preflight", "OPENAI_API_KEY", "private-token"),
            ("api", "AI_MODEL", "private-model"),
            ("worker", "ALLOW_EXTERNAL_AI_RESTRICTED", "true"),
            ("worker", "AI_LOCAL_EXPERIMENTAL_ENABLED", "true"),
            ("api", "AI_PRODUCTION_CONTROL_PLANE_ENABLED", "true"),
            ("external-evidence-observation-worker", "EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED", "true"),
            ("external-evidence-observation-worker", "EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED", "true"),
            ("migrate", "OPENAI_API_KEY", "secret-elsewhere"),
            ("web", "AI_MODEL", "unknown-model"),
        ):
            with self.subTest(service=name, field=key):
                data = safe_compose()
                data["services"][name]["environment"][key] = value
                result = inspect_config(data, release_sha=SHA)
                self.assertFalse(result["compose_ai_and_adapter_config_safe"])
                self.assertTrue(result["check_failures"])
                self.assertNotIn(value, json.dumps(result))

    def test_unknown_or_missing_services_and_malformed_inputs_are_rejected(self):
        tests = (
            lambda c: c["services"].update({"malicious-container": {"environment": {}}}),
            lambda c: c["services"].pop("worker"),
            lambda c: c["services"].update({"api": []}),
            lambda c: c["services"]["api"].update({"environment": []}),
            lambda c: c["services"]["worker"]["environment"].pop("OCR_ENABLED"),
            lambda c: c["services"]["worker"]["environment"].pop("OCR_LANGUAGES"),
        )
        for change in tests:
            data = safe_compose()
            change(data)
            result = inspect_config(data, release_sha=SHA)
            self.assertFalse(result["compose_ai_and_adapter_config_safe"])
        for bad in (None, [], {}, {"services": []}):
            with self.assertRaises(ComposeScopeError):
                inspect_config(bad, release_sha=SHA)
        for bad in ("bad", "", None, True):
            with self.assertRaises(ComposeScopeError):
                inspect_config(safe_compose(), release_sha=bad)

    def test_private_observation_write_is_exclusive_and_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "readback.json"
            private_env = Path(directory) / "private.env"
            private_env.write_text("SECRET=private-secret\n", encoding="utf-8")
            docker_reply = json.dumps(safe_compose())
            out = StringIO()
            with patch(
                "scripts.pilot_rc_compose_feature_observation.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["docker"], returncode=0, stdout=docker_reply, stderr="private-secret",
                ),
            ), redirect_stdout(out):
                self.assertEqual(0, main([
                    "--env-file", str(private_env), "--release-sha", SHA, "--output", str(output),
                ]))
            self.assertTrue(output.is_file())
            self.assertNotIn("private-secret", output.read_text(encoding="utf-8"))
            self.assertNotIn("private-secret", out.getvalue())
            self.assertFalse(json.loads(output.read_text())["pilot_accepted"])
            if os.name != "nt":
                self.assertEqual(0o600, output.stat().st_mode & 0o777)

            output_text = StringIO()
            with patch(
                "scripts.pilot_rc_compose_feature_observation.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["docker"], returncode=0, stdout=docker_reply, stderr="private-secret",
                ),
            ), redirect_stderr(output_text):
                self.assertEqual(2, main([
                    "--env-file", str(private_env), "--release-sha", SHA, "--output", str(output),
                ]))
            self.assertNotIn("private-secret", output_text.getvalue())

    def test_invalid_docker_output_never_leaks_sensitive_content(self):
        with tempfile.TemporaryDirectory() as directory:
            private_env = Path(directory) / "private.env"
            private_env.write_text("PASSWORD=private-secret\n", encoding="utf-8")
            for response in (
                subprocess.CompletedProcess(["docker"], 1, stdout="", stderr="private-secret"),
                subprocess.CompletedProcess(["docker"], 0, stdout="private-secret", stderr=""),
                subprocess.CompletedProcess(["docker"], 0, stdout="x" * 2_000_001, stderr=""),
            ):
                with self.subTest(response=response.returncode):
                    with patch(
                        "scripts.pilot_rc_compose_feature_observation.subprocess.run",
                        return_value=response,
                    ):
                        with self.assertRaises(ComposeScopeError) as caught:
                            observe_config(env_file=private_env)
                    self.assertNotIn("private-secret", str(caught.exception))
            self.assertTrue(COMPOSE.name == "docker-compose.yml")


if __name__ == "__main__":
    unittest.main()

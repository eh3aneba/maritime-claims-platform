"""Offline fail-closed tests for sanitized running-container AI flag observation."""
from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.pilot_compose_readiness import EXPECTED, HEALTHY, ONESHOT
from scripts import pilot_rc_running_ai_env_readback as probe

SHA = "a" * 40


def compose_items():
    result = []
    for index, name in enumerate(EXPECTED):
        result.append({
            "Service": name, "ID": f"{index + 1:064x}",
            "State": "exited" if name in ONESHOT else "running",
            "Health": "healthy" if name in HEALTHY else "none",
            "ExitCode": 0,
        })
    return result


def safe_envs():
    out = {name: ["PATH=/usr/bin", "DATABASE_URL=postgres://private:secret@db"] for name in EXPECTED}
    for name in ("api", "preflight", "worker"):
        out[name] += [
            "AI_PROVIDER=disabled",
            "AI_MODEL=",
            "OPENAI_API_KEY=",
            "ALLOW_EXTERNAL_AI_RESTRICTED=false",
        ]
    out["worker"] += ["OCR_ENABLED=true", "OCR_LANGUAGES=eng+fas"]
    return out


class RunningAIReadbackTests(unittest.TestCase):
    def test_safe_runtime_readback_is_bounded_and_never_pilot_authorization(self):
        a = compose_items()
        result = probe.summarize(
            before=a, after=deepcopy(a),
            environment_by_service=safe_envs(), release_sha=SHA,
        )
        self.assertTrue(result["runtime_ai_config_disabled_observed"])
        self.assertTrue(result["container_identity_stable"])
        self.assertEqual(result["expected_service_count"], len(EXPECTED))
        self.assertEqual(result["inspected_service_count"], len(EXPECTED))
        for key in (
            "actual_egress_isolation_attested",
            "database_connector_state_attested",
            "persian_critical_extraction_disabled_attested",
            "persian_ocr_semantics_attested",
            "source_sha_to_image_verified",
            "independent_operator_verified",
            "real_customer_data_authorized", "pilot_accepted",
        ):
            self.assertIs(result[key], False)
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("postgres://", json.dumps(result))

    def test_enabled_ai_secret_adapters_or_model_fail_without_disclosing_values(self):
        cases = (
            ("api", "AI_PROVIDER=openai"),
            ("worker", "AI_PROVIDER=ollama_local"),
            ("preflight", "OPENAI_API_KEY=extremely-private-key"),
            ("api", "AI_MODEL=private-ai-model"),
            ("worker", "ALLOW_EXTERNAL_AI_RESTRICTED=true"),
            ("worker", "AI_LOCAL_EXPERIMENTAL_ENABLED=true"),
            ("api", "AI_PRODUCTION_CONTROL_PLANE_ENABLED=true"),
            ("external-evidence-observation-worker", "EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED=true"),
            ("external-evidence-review-projector-worker", "EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED=true"),
            ("migrate", "OPENAI_API_KEY=other-private-token"),
            ("web", "AI_MODEL=another-private-model"),
        )
        for service, field in cases:
            with self.subTest(service=service, field=field.split("=")[0]):
                env = safe_envs()
                name, _ = field.split("=", 1)
                env[service] = [v for v in env[service] if not v.startswith(name + "=")]
                env[service].append(field)
                result = probe.summarize(
                    before=compose_items(), after=compose_items(),
                    environment_by_service=env, release_sha=SHA,
                )
                self.assertFalse(result["runtime_ai_config_disabled_observed"])
                self.assertTrue(result["check_failures"])
                self.assertNotIn(field, json.dumps(result))

    def test_missing_duplicate_or_malformed_env_fail_closed(self):
        for mutation in (
            lambda x: x["api"].remove("AI_PROVIDER=disabled"),
            lambda x: x["api"].append("AI_PROVIDER=disabled"),
            lambda x: x["worker"].remove("OCR_ENABLED=true"),
            lambda x: x["worker"].remove("OCR_LANGUAGES=eng+fas"),
            lambda x: x["api"].append("not-a-key-value"),
            lambda x: x["api"].append(None),
        ):
            env = safe_envs()
            mutation(env)
            result = probe.summarize(
                before=compose_items(), after=compose_items(),
                environment_by_service=env, release_sha=SHA,
            )
            self.assertFalse(result["runtime_ai_config_disabled_observed"])
        with self.assertRaises(probe.RuntimeScopeError):
            probe.summarize(
                before=compose_items(), after=compose_items(),
                environment_by_service={"api": []}, release_sha=SHA,
            )

    def test_container_drift_unready_duplicate_and_optional_demo_protections(self):
        a = compose_items()
        for b in (
            a[:-1],
            [{**x, "ID": "f" * 64} if x["Service"] == "api" else x for x in a],
            [*a, a[0]],
            [{**x, "State": "restarting"} if x["Service"] == "api" else x for x in a],
        ):
            with self.assertRaises(probe.RuntimeScopeError):
                probe.summarize(
                    before=a, after=b,
                    environment_by_service=safe_envs(), release_sha=SHA,
                )
        demo = {"Service": "demo-seed", "ID": "f" * 64,
                "State": "exited", "Health": "none", "ExitCode": 0}
        with_demo = [*a, demo]
        environment = safe_envs() | {"demo-seed": ["AI_PROVIDER=disabled"]}
        ok = probe.summarize(
            before=with_demo, after=deepcopy(with_demo),
            environment_by_service=environment, release_sha=SHA,
        )
        self.assertEqual(len(EXPECTED) + 1, ok["inspected_service_count"])
        environment["demo-seed"] = ["AI_PROVIDER=openai"]
        bad = probe.summarize(
            before=with_demo, after=deepcopy(with_demo),
            environment_by_service=environment, release_sha=SHA,
        )
        self.assertFalse(bad["runtime_ai_config_disabled_observed"])

    def test_docker_inspect_secret_never_enters_error_or_report(self):
        cid = "f" * 64
        private = json.dumps([{"Id": cid, "Config": {"Env": [
            "PASSWORD=top-secret", "AI_PROVIDER=disabled",
        ]}}])
        with patch.object(
            probe.subprocess, "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=private, stderr="other-secret",
            ),
        ) as run:
            self.assertEqual(
                probe._read_config_env(cid),
                ["PASSWORD=top-secret", "AI_PROVIDER=disabled"],
            )
            self.assertEqual(run.call_args.args[0],
                             ["docker", "inspect", "--type", "container", cid])
        for code, content in ((1, "top-secret"), (0, "unparseable-top-secret")):
            with patch.object(
                probe.subprocess, "run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=code, stdout=content, stderr="other-secret",
                ),
            ):
                with self.assertRaises(probe.RuntimeScopeError) as caught:
                    probe._read_config_env(cid)
                self.assertNotIn("secret", str(caught.exception))

    def test_cli_saves_exclusive_sanitized_private_record_without_live_docker(self):
        a = compose_items()
        ids = probe._observed_ids(a)
        by_id = {cid: safe_envs()[service] for service, cid in ids.items()}
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "readback.json"
            with patch.object(probe, "observe", side_effect=[a, deepcopy(a)]), \
                 patch.object(probe, "_read_config_env", side_effect=lambda x: by_id[x]):
                with redirect_stdout(StringIO()) as output:
                    code = probe.main([
                        "--env-file", "private.env",
                        "--release-sha", SHA, "--output", str(destination),
                    ])
            self.assertEqual(code, 0)
            self.assertIn("NOT egress", output.getvalue())
            stored = destination.read_text(encoding="utf-8")
            self.assertNotIn("private:", stored)
            self.assertTrue(json.loads(stored)["runtime_ai_config_disabled_observed"])
            if os.name != "nt":
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            with patch.object(probe, "observe", side_effect=[a, deepcopy(a)]), \
                 patch.object(probe, "_read_config_env", side_effect=lambda x: by_id[x]):
                with redirect_stderr(StringIO()) as errors:
                    self.assertEqual(2, probe.main([
                        "--env-file", "private.env",
                        "--release-sha", SHA, "--output", str(destination),
                    ]))
            self.assertNotIn("private:", errors.getvalue())

    def test_operator_script_and_module_invocations_both_work_without_pythonpath(self):
        root = Path(__file__).resolve().parents[2]
        entry = root / "scripts" / "pilot_rc_running_ai_env_readback.py"
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        for command in (
            [sys.executable, str(entry), "--help"],
            [sys.executable, "-m", "scripts.pilot_rc_running_ai_env_readback", "--help"],
        ):
            with self.subTest(command=command[1:]):
                run = subprocess.run(
                    command, cwd=root, env=environment,
                    capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(run.returncode, 0, run.stderr[:500])
                self.assertIn("--release-sha", run.stdout)


if __name__ == "__main__":
    unittest.main()

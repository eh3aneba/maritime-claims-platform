"""No-Docker regression for same-census first manual synthetic H&M observation."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import pilot_first_manual_hm_census as probe
from scripts import pilot_compose_readiness as readiness
from scripts import pilot_running_image_identity as images

SHA = "a" * 40


def compose_config():
    services = {name: {"environment": {}} for name in readiness.EXPECTED}
    for name in probe.rendered.PILOT_APP_ENV_SERVICES:
        services[name]["environment"]["APP_ENV"] = "pilot"
    for name in ("api", "preflight", "worker"):
        services[name]["environment"].update({
            "AI_PROVIDER": "disabled",
            "AI_MODEL": "",
            "OPENAI_API_KEY": "",
            "ALLOW_EXTERNAL_AI_RESTRICTED": "false",
        })
    for name in ("worker", "preflight"):
        services[name]["environment"]["OCR_ENABLED"] = "false"
    services["worker"]["environment"]["OCR_LANGUAGES"] = "eng+fas"
    for key in (
        "AI_LOCAL_EXPERIMENTAL_ENABLED",
        "AI_PRODUCTION_CONTROL_PLANE_ENABLED",
        "EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED",
        "EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED",
    ):
        services["preflight"]["environment"][key] = "false"
    return {"services": services}


def containers():
    rows = []
    for n, name in enumerate(readiness.EXPECTED):
        rows.append({
            "Service": name,
            "ID": f"{n + 1:064x}",
            "State": "exited" if name in readiness.ONESHOT else "running",
            "Health": "healthy" if name in readiness.HEALTHY else "none",
            "ExitCode": 0,
        })
    return rows


def runtime_envs():
    env = {name: ["PATH=/usr/bin", "DATABASE_URL=postgresql://private:password@db"]
           for name in readiness.EXPECTED}
    for name in probe.rendered.PILOT_APP_ENV_SERVICES:
        env[name].append("APP_ENV=pilot")
    for name in ("api", "preflight", "worker"):
        env[name] += [
            "AI_PROVIDER=disabled", "AI_MODEL=",
            "OPENAI_API_KEY=", "ALLOW_EXTERNAL_AI_RESTRICTED=false",
        ]
    for name in ("worker", "preflight"):
        env[name].append("OCR_ENABLED=false")
    env["worker"].append("OCR_LANGUAGES=eng+fas")
    env["preflight"] += [
        "AI_LOCAL_EXPERIMENTAL_ENABLED=false",
        "AI_PRODUCTION_CONTROL_PLANE_ENABLED=false",
        "EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED=false",
        "EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED=false",
    ]
    return env


def image_ids():
    return {name: "sha256:" + f"{i + 1:064x}"
            for i, name in enumerate(readiness.EXPECTED)}


class FirstManualHMCensusTests(unittest.TestCase):
    def test_good_same_census_is_bounded_pass_never_pilot_go(self):
        data = probe.assess(
            config=compose_config(), before=containers(), after=containers(),
            environment_by_service=runtime_envs(),
            observed_images=image_ids(), expected_images=image_ids(),
            release_sha=SHA,
        )
        self.assertEqual(data["schema"], probe.SCHEMA)
        self.assertTrue(data["bounded_same_census_passed"])
        self.assertEqual(set(data["checks"]), {
            "rendered_compose_manual_scope_safe",
            "same_census_service_status_complete",
            "effective_manual_hm_ai_ocr_adapters_off",
            "stable_container_image_ids_match_private_manifest",
        })
        self.assertTrue(all(data["checks"].values()))
        self.assertEqual(data["expected_service_count"], 11)
        for name in (
            "selected_host_independently_verified",
            "registry_digest_and_source_provenance_verified",
            "actual_network_egress_isolation_verified",
            "database_external_connectors_verified_disabled",
            "paired_evidence_postgres_recovery_verified",
            "rollback_and_alert_ownership_verified",
            "independent_security_and_hm_approvals_verified",
            "real_customer_data_authorized",
            "pilot_authorized",
        ):
            self.assertIs(data[name], False)
        self.assertNotIn("password", json.dumps(data))
        self.assertNotIn("postgresql://", json.dumps(data))
        self.assertNotIn("sha256:", json.dumps(data))

    def test_bad_real_ocr_ai_flag_and_image_mismatch_fail_closed(self):
        for mode in ("worker_ocr", "preflight_ocr", "ai", "image_mismatch"):
            with self.subTest(mode=mode):
                env = runtime_envs()
                observed = image_ids()
                if mode == "worker_ocr":
                    env["worker"] = [
                        "OCR_ENABLED=true" if v == "OCR_ENABLED=false" else v
                        for v in env["worker"]
                    ]
                elif mode == "preflight_ocr":
                    env["preflight"] = [
                        "OCR_ENABLED=true" if v == "OCR_ENABLED=false" else v
                        for v in env["preflight"]
                    ]
                elif mode == "ai":
                    env["worker"] = [
                        "AI_PROVIDER=openai" if v == "AI_PROVIDER=disabled" else v
                        for v in env["worker"]
                    ]
                else:
                    observed["worker"] = "sha256:" + "f" * 64
                result = probe.assess(
                    config=compose_config(), before=containers(), after=containers(),
                    environment_by_service=env, observed_images=observed,
                    expected_images=image_ids(), release_sha=SHA,
                )
                self.assertFalse(result["bounded_same_census_passed"])
                self.assertFalse(result["pilot_authorized"])
                self.assertNotIn("password", json.dumps(result))

    def test_same_census_rejects_db_worker_mixed_app_env_without_authorization(self):
        # Synthetic MT ORION can only be considered within the bounded pilot
        # environment if all live DB-connected worker processes share APP_ENV.
        for name in probe.rendered.PILOT_APP_ENV_SERVICES - {
            "api", "preflight", "worker",
        }:
            with self.subTest(service=name):
                env = runtime_envs()
                env[name] = ["APP_ENV=production" if x == "APP_ENV=pilot" else x
                             for x in env[name]]
                result = probe.assess(
                    config=compose_config(), before=containers(), after=containers(),
                    environment_by_service=env,
                    observed_images=image_ids(), expected_images=image_ids(),
                    release_sha=SHA,
                )
                self.assertFalse(result["bounded_same_census_passed"])
                self.assertFalse(result["checks"]["effective_manual_hm_ai_ocr_adapters_off"])
                self.assertFalse(result["pilot_authorized"])
                self.assertNotIn("password", json.dumps(result))
                config = compose_config()
                config["services"][name]["environment"].pop("APP_ENV")
                with self.assertRaises(probe.SnapshotError):
                    probe.assess(
                        config=config, before=containers(), after=containers(),
                        environment_by_service=runtime_envs(),
                        observed_images=image_ids(), expected_images=image_ids(),
                        release_sha=SHA,
                    )

    def test_different_container_ids_or_unhealthy_and_unexpected_service_rejected(self):
        before = containers()
        for changed in (
            [{**row, "ID": "f" * 64} if row["Service"] == "api" else row
             for row in before],
            [{**row, "State": "dead"} if row["Service"] == "api" else row
             for row in before],
            [*before, {"Service": "rogue", "State": "running", "ID": "f" * 64}],
        ):
            with self.subTest(change=changed[-1].get("Service")):
                with self.assertRaises((probe.runtime.RuntimeScopeError,
                                        images.ImageIdentityError)):
                    probe.assess(
                        config=compose_config(), before=before, after=changed,
                        environment_by_service=runtime_envs(),
                        observed_images=image_ids(), expected_images=image_ids(),
                        release_sha=SHA,
                    )

    def test_unsafe_rendered_compose_never_passes_even_if_runtime_mock_is_safe(self):
        for edit in ("worker_ocr", "sftp"):
            with self.subTest(edit=edit):
                cfg = compose_config()
                if edit == "worker_ocr":
                    cfg["services"]["worker"]["environment"]["OCR_ENABLED"] = "true"
                else:
                    cfg["services"]["preflight"]["environment"][
                        "EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED"
                    ] = "true"
                with self.assertRaises(probe.SnapshotError):
                    probe.assess(
                        config=cfg, before=containers(), after=containers(),
                        environment_by_service=runtime_envs(),
                        observed_images=image_ids(), expected_images=image_ids(),
                        release_sha=SHA,
                    )

    def test_invalid_release_identity_rejected(self):
        with self.assertRaises(probe.SnapshotError):
            probe.assess(
                config=compose_config(), before=containers(), after=containers(),
                environment_by_service=runtime_envs(),
                observed_images=image_ids(), expected_images=image_ids(),
                release_sha="not-a-full-sha",
            )

    def test_private_files_and_same_census_order_in_operator_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("FAKE_PASSWORD=synthetic-private-value\n", encoding="utf-8")
            env_file.chmod(0o600)
            manifest = Path(directory) / "approved-image-ids.json"
            data = images.manifest_template(SHA)
            data["expected_image_ids"] = image_ids()
            manifest.write_text(json.dumps(data), encoding="utf-8")
            manifest.chmod(0o600)
            output = Path(directory) / "same-census.json"
            rows = containers()
            envs = runtime_envs()
            ids = {row["ID"]: row["Service"] for row in rows}
            calls = []
            def observe_rows(*, env_file):
                calls.append("ps")
                return deepcopy(rows)
            def read_env(cid):
                calls.append("env")
                return envs[ids[cid]]
            def inspect_images(items):
                calls.append("image")
                return image_ids()
            with patch.object(probe.target, "observe", side_effect=lambda: calls.append("target")), \
                 patch.object(probe.rendered, "observe_config",
                              side_effect=lambda **_: calls.append("config") or compose_config()), \
                 patch.object(probe.readiness, "observe", side_effect=observe_rows), \
                 patch.object(probe.runtime, "_read_config_env", side_effect=read_env), \
                 patch.object(probe.images, "inspect_image_ids", side_effect=inspect_images):
                with redirect_stdout(StringIO()) as stdout:
                    result = probe.main([
                        "--env-file", str(env_file), "--manifest", str(manifest),
                        "--release-sha", SHA, "--output", str(output),
                    ])
            self.assertEqual(result, 0)
            self.assertTrue(output.exists())
            self.assertIn("NOT a verified host", stdout.getvalue())
            self.assertEqual(calls[0:2], ["target", "config"])
            self.assertEqual(calls.count("ps"), 2)
            self.assertEqual(calls.count("env"), len(readiness.EXPECTED))
            self.assertEqual(calls.count("image"), 1)
            self.assertLess(calls.index("ps"), calls.index("env"))
            self.assertLess(calls.index("env"), calls.index("image"))
            self.assertEqual(calls[-1], "ps")
            stored = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(stored["bounded_same_census_passed"])
            self.assertFalse(stored["pilot_authorized"])
            self.assertNotIn("synthetic-private-value", json.dumps(stored))
            self.assertNotIn("PASSWORD=", json.dumps(stored))
            if os.name != "nt":
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            # Exclusive output must never overwrite a prior private record.
            with patch.object(probe.target, "observe"), \
                 patch.object(probe.rendered, "observe_config", return_value=compose_config()), \
                 patch.object(probe.readiness, "observe", side_effect=[rows, rows]), \
                 patch.object(probe.runtime, "_read_config_env", side_effect=read_env), \
                 patch.object(probe.images, "inspect_image_ids", return_value=image_ids()):
                with redirect_stderr(StringIO()) as err:
                    self.assertEqual(2, probe.main([
                        "--env-file", str(env_file), "--manifest", str(manifest),
                        "--release-sha", SHA, "--output", str(output),
                    ]))
            self.assertNotIn("synthetic-private-value", err.getvalue())

    def test_remote_context_and_insecure_env_block_before_docker_ps(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / ".env"
            file.write_text("PRIVATE=never-log\n", encoding="utf-8")
            file.chmod(0o600)
            manifest = Path(directory) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            manifest.chmod(0o600)
            with patch.object(probe.target, "observe",
                              side_effect=probe.target.DockerTargetError("remote target")), \
                 patch.object(probe.readiness, "observe") as observe:
                with redirect_stderr(StringIO()) as err:
                    self.assertEqual(2, probe.main([
                        "--env-file", str(file), "--manifest", str(manifest),
                        "--release-sha", SHA,
                        "--output", str(Path(directory) / "record.json"),
                    ]))
                observe.assert_not_called()
                self.assertNotIn("remote target", err.getvalue())
            if os.name == "posix":
                file.chmod(0o644)
                with patch.object(probe.target, "observe") as target:
                    with redirect_stderr(StringIO()):
                        self.assertEqual(2, probe.main([
                            "--env-file", str(file), "--manifest", str(manifest),
                            "--release-sha", SHA,
                            "--output", str(Path(directory) / "record2.json"),
                        ]))
                    target.assert_not_called()
            link = Path(directory) / "linked.env"
            try:
                link.symlink_to(file)
            except (OSError, NotImplementedError):
                pass
            else:
                with patch.object(probe.target, "observe") as target:
                    with redirect_stderr(StringIO()):
                        self.assertEqual(2, probe.main([
                            "--env-file", str(link), "--manifest", str(manifest),
                            "--release-sha", SHA,
                            "--output", str(Path(directory) / "record3.json"),
                        ]))
                    target.assert_not_called()

    def test_entrypoint_works_without_pythonpath_and_never_needs_docker_for_help(self):
        root = Path(__file__).resolve().parents[2]
        script = root / "scripts" / "pilot_first_manual_hm_census.py"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        for command in (
            [sys.executable, str(script), "--help"],
            [sys.executable, "-m", "scripts.pilot_first_manual_hm_census", "--help"],
        ):
            with self.subTest(command=command):
                result = subprocess.run(
                    command, cwd=root, env=env, capture_output=True,
                    text=True, timeout=15, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr[:500])
                self.assertIn("--manifest", result.stdout)


if __name__ == "__main__":
    unittest.main()

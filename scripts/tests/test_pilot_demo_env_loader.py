"""Offline regressions for non-evaluating MT ORION .env import."""
from __future__ import annotations

import io
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_demo_env_loader as loader  # noqa: E402


def valid_lines() -> str:
    return """# synthetic only
APP_ENV=test
APP_NAME="Maritime Claims & Risk Intelligence Platform"
MCRI_SYNTHETIC_ONLY_CONFIRM=YES
AI_PROVIDER=disabled
AI_MODEL=
ALLOW_EXTERNAL_AI_RESTRICTED=false
AI_LOCAL_EXPERIMENTAL_ENABLED=false
AI_PRODUCTION_CONTROL_PLANE_ENABLED=false
EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED=false
EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED=false
OCR_ENABLED=false
MALWARE_SCAN_ENABLED=true
STORAGE_BACKEND=local
POSTGRES_DB=mcri_ci
POSTGRES_USER=mcri_ci
DATABASE_URL=postgresql+psycopg://mcri_ci:private-test-password@db:5432/mcri_ci
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api/v1
MCRI_DEMO_PASSWORD=private-demo-password
OPENAI_API_KEY=
"""


class SafeDemoEnvImportTests(unittest.TestCase):
    def test_allow_literal_ci_and_pilot_values_with_quoted_app_name(self):
        parsed = loader.parse_env(valid_lines())
        self.assertEqual(parsed["APP_NAME"], "Maritime Claims & Risk Intelligence Platform")
        self.assertEqual(parsed["OPENAI_API_KEY"], "")
        self.assertEqual(parsed["APP_ENV"], "test")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.ci"
            path.write_text(valid_lines(), encoding="utf-8")
            self.assertEqual(loader.load(path), parsed)
            path.write_text(valid_lines().replace("APP_ENV=test", "APP_ENV=pilot"))
            self.assertEqual(loader.load(path)["APP_ENV"], "pilot")

    def test_loader_emits_literal_nul_terminated_records_no_secret_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.ci"
            path.write_text(valid_lines())
            buffer = io.BytesIO()
            writer = io.TextIOWrapper(buffer, encoding="utf-8")
            with patch.object(loader.sys, "stdout", writer):
                self.assertEqual(loader.main([str(path)]), 0)
            writer.flush()
            values = buffer.getvalue().split(b"\0")
            self.assertEqual(values[-1], b"")
            self.assertIn(b"APP_NAME=Maritime Claims & Risk Intelligence Platform", values)
            self.assertIn(b"MCRI_SYNTHETIC_ONLY_CONFIRM=YES", values)
            self.assertIn(b"OPENAI_API_KEY=", values)

    def test_one_read_produces_private_frozen_compose_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "mutable.env"
            frozen = Path(directory) / "frozen.env"
            source.write_text(valid_lines(), encoding="utf-8")
            buffer = io.BytesIO()
            writer = io.TextIOWrapper(buffer, encoding="utf-8")
            with patch.object(loader.sys, "stdout", writer):
                self.assertEqual(
                    loader.main([str(source), "--snapshot", str(frozen)]), 0
                )
            writer.flush()
            self.assertIn(b"APP_ENV=test\0", buffer.getvalue())
            self.assertEqual(
                loader.parse_env(frozen.read_text(encoding="utf-8")),
                loader.parse_env(valid_lines()),
            )
            self.assertEqual(frozen.stat().st_mode & 0o777, 0o600)
            self.assertIn(
                'APP_NAME="Maritime Claims & Risk Intelligence Platform"',
                frozen.read_text(),
            )
            source.write_text(valid_lines().replace("APP_ENV=test", "APP_ENV=production"))
            # Docker and Bash now consume the SAME frozen, verified content.
            self.assertEqual(loader.load(frozen)["APP_ENV"], "test")

    def test_invalid_or_existing_snapshot_never_emits_untrusted_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.env"
            frozen = Path(directory) / "frozen.env"
            source.write_text(valid_lines() + "SECRET_KEY=$(private_token)\n")
            out = io.BytesIO()
            writer = io.TextIOWrapper(out, encoding="utf-8")
            errors = io.StringIO()
            with patch.object(loader.sys, "stdout", writer), patch.object(
                loader.sys, "stderr", errors
            ):
                self.assertEqual(
                    loader.main([str(source), "--snapshot", str(frozen)]), 2
                )
            writer.flush()
            self.assertFalse(frozen.exists())
            self.assertEqual(out.getvalue(), b"")
            self.assertNotIn("private_token", errors.getvalue())
            source.write_text(valid_lines())
            frozen.write_text("protected-original-record")
            with patch.object(loader.sys, "stderr", io.StringIO()):
                self.assertEqual(
                    loader.main([str(source), "--snapshot", str(frozen)]), 2
                )
            self.assertEqual(frozen.read_text(), "protected-original-record")

    def test_shell_expression_and_unsafe_environment_entries_never_accepted(self):
        for bad in (
            "HOOK=$(touch /tmp/synthetic-danger)",
            "HOOK=`echo secret`",
            "POSTGRES_PASSWORD=private$({touch})",
            "POSTGRES_PASSWORD=private\\secret",
            "BASH_ENV=/tmp/malicious",
            "LD_PRELOAD=/tmp/inject.so",
            "PYTHONPATH=/tmp/inject",
            "DOCKER_HOST=tcp://remote.example:2375",
            "DOCKER_CONTEXT=customer-prod",
            "COMPOSE_PROJECT_NAME=customer",
            "COMPOSE_FILE=/tmp/untrusted-compose.yml",
            "COMPOSE_ENV_FILES=/tmp/customer.env",
            "PATH=/tmp/inject",
            "BASHOPTS=x",
            "MCRI_DEMO_PASSWORD=private-demo-password; echo bad",
            "export MALWARE_SCAN_ENABLED=true",
            "MCRI_TEST='unterminated",
            "KEY=\"unterminated",
            "POSTGRES_DB= duplicate",
            "POSTGRES_DB=mcri_ci",  # duplicate key
            "not-an-assignment",
            'UNQUOTED=value"danger',
        ):
            with self.subTest(bad=bad.split("=")[0]):
                with self.assertRaises(loader.SyntheticEnvError):
                    loader.parse_env(valid_lines() + bad + "\n")

    def test_allowlist_matches_documented_template_and_compose_contract(self):
        root = Path(__file__).resolve().parents[2]
        template = (root / ".env.pilot.example").read_text(encoding="utf-8")
        compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
        expected = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", template, re.M))
        expected.update(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", compose))
        expected.add("MCRI_SYNTHETIC_ONLY_CONFIRM")
        self.assertEqual(loader.ALLOWED_KEYS, expected)

    def test_shell_control_and_unreviewed_keys_rejected_before_export(self):
        for key in (
            "MCRI_PRIVATE_TMP", "ENV_FILE", "BASH_XTRACEFD", "SHELLOPTS",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE",
            "GITHUB_ENV", "GITHUB_PATH", "UNREVIEWED_FEATURE",
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "source.env"
                frozen = Path(directory) / "frozen.env"
                source.write_text(valid_lines() + key + "=private-marker\n")
                out = io.BytesIO()
                writer = io.TextIOWrapper(out, encoding="utf-8")
                errors = io.StringIO()
                with patch.object(loader.sys, "stdout", writer), patch.object(
                    loader.sys, "stderr", errors
                ):
                    self.assertEqual(
                        loader.main([str(source), "--snapshot", str(frozen)]), 2
                    )
                writer.flush()
                self.assertEqual(out.getvalue(), b"")
                self.assertFalse(frozen.exists())
                self.assertNotIn("private-marker", errors.getvalue())

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Bash operator path")
    def test_preflight_checks_whole_engine_for_pilot_before_any_start(self):
        root = Path(__file__).resolve().parents[2]
        # Stubs run only in this private temp directory, never connect to
        # Docker. The Python loader and seed guard are the real implementations.
        for mode in ("test", "pilot"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                d = Path(directory)
                source = d / "operator.env"
                source.write_text(valid_lines().replace("APP_ENV=test", "APP_ENV=" + mode))
                log = d / "calls"
                fake_python = d / "python"
                fake_docker = d / "docker"
                fake_python.write_text(
                    "#!/bin/sh\n"
                    "case \"$1\" in\n"
                    "  scripts/pilot_demo_env_loader.py|scripts/pilot_demo_seed_guard.py)\n"
                    "    exec " + shlex.quote(sys.executable) + " \"$@\" ;;\n"
                    "  scripts/pilot_demo_docker_target.py|scripts/pilot_compose_port_policy.py)\n"
                    "    exit 0 ;;\n"
                    "  scripts/pilot_demo_empty_stack.py)\n"
                    "    printf '%s\\n' \"$@\" > " + shlex.quote(str(log)) + "\n"
                    "    exit 87 ;;\n"
                    "esac\nexit 91\n"
                )
                fake_docker.write_text(
                    "#!/bin/sh\n"
                    "case \"$*\" in\n"
                    "  'compose version'|*'config') exit 0 ;;\n"
                    "  *) exit 92 ;;\n"
                    "esac\n"
                )
                fake_python.chmod(0o700)
                fake_docker.chmod(0o700)
                env = {"PATH": str(d) + os.pathsep + os.defpath,
                       "HOME": str(d), "TMPDIR": str(d)}
                proc = subprocess.run(
                    [shutil.which("bash"), str(root / "scripts/design_partner_preflight.sh"),
                     str(source)],
                    cwd=root, env=env, capture_output=True, text=True,
                    check=False, timeout=20,
                )
                # Our empty-host stub refuses immediately: no build, seed,
                # health request or execution against any actual Engine.
                self.assertEqual(proc.returncode, 87, msg=proc.stderr)
                args = log.read_text().splitlines()
                self.assertEqual(args[0:2], ["scripts/pilot_demo_empty_stack.py", "--env-file"])
                snapshot = Path(args[2])
                self.assertEqual(snapshot.name, "frozen.env")
                self.assertEqual(snapshot.parent.parent, d)
                self.assertFalse(snapshot.exists())
                self.assertEqual(args[3:], ["--strict-empty-docker-host"] if mode == "pilot" else [])

    def test_validation_is_from_file_not_ambient_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.env"
            data = valid_lines().replace(
                "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api/v1",
                "NEXT_PUBLIC_API_BASE_URL=https://customer.example/api/v1",
            )
            path.write_text(data)
            with patch.dict(loader.sys.modules["os"].environ, {
                "NEXT_PUBLIC_API_BASE_URL": "http://127.0.0.1:8000/api/v1"
            }):
                with self.assertRaises(loader.DemoSeedGuardError):
                    loader.load(path)
            path.write_text(valid_lines().replace("MCRI_SYNTHETIC_ONLY_CONFIRM=YES", ""))
            with self.assertRaises(loader.DemoSeedGuardError):
                loader.load(path)
            path.write_text(valid_lines() + "SECRET_KEY=REPLACE_WITH_SOMETHING\n")
            with self.assertRaises(loader.SyntheticEnvError):
                loader.load(path)

    def test_unsafe_file_does_not_emit_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(valid_lines() + "EVIL=$(VERY_PRIVATE_SECRET)\n")
            output = io.BytesIO()
            writer = io.TextIOWrapper(output, encoding="utf-8")
            errors = io.StringIO()
            with patch.object(loader.sys, "stdout", writer), patch.object(loader.sys, "stderr", errors):
                self.assertEqual(loader.main([str(path)]), 2)
            writer.flush()
            self.assertEqual(output.getvalue(), b"")
            self.assertNotIn("VERY_PRIVATE_SECRET", errors.getvalue())


if __name__ == "__main__":
    unittest.main()

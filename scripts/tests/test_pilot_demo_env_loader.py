"""Offline regressions for non-evaluating MT ORION .env import."""
from __future__ import annotations

import io
from pathlib import Path
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
            self.assertIn(b"APP_ENV=test\\0", buffer.getvalue())
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
            source.write_text(valid_lines() + "SECRET_KEY=$(private_token)\\n")
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

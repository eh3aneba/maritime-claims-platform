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

"""Offline, no-Docker regression for pre-seed synthetic-only safety guard."""
from __future__ import annotations

from copy import deepcopy
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_demo_seed_guard as guard  # noqa: E402


def fixture() -> dict[str, str]:
    return {
        "MCRI_SYNTHETIC_ONLY_CONFIRM": "YES",
        "APP_ENV": "test",
        "AI_PROVIDER": "disabled",
        "MALWARE_SCAN_ENABLED": "true",
        "STORAGE_BACKEND": "local",
        "POSTGRES_DB": "isolated_mcri_test",
        "POSTGRES_USER": "test_runner",
        "DATABASE_URL": (
            "postgresql+psycopg://test_runner:synthetic-private-secret"
            "@db:5432/isolated_mcri_test"
        ),
        "NEXT_PUBLIC_API_BASE_URL": "http://127.0.0.1:8000/api/v1",
    }


class SyntheticDemoSeedGateTests(unittest.TestCase):
    def test_explicit_test_and_pilot_accept_without_proving_host(self):
        sample = fixture()
        self.assertIsNone(guard.check(sample))
        sample["APP_ENV"] = "pilot"
        self.assertIsNone(guard.check(sample))

    def test_missing_or_incorrect_confirmation_fails(self):
        for value in ("", "yes", "TRUE", "NO"):
            sample = fixture()
            sample["MCRI_SYNTHETIC_ONLY_CONFIRM"] = value
            with self.subTest(confirmation=value), self.assertRaises(guard.DemoSeedGuardError):
                guard.check(sample)
        sample = fixture()
        sample.pop("MCRI_SYNTHETIC_ONLY_CONFIRM")
        with self.assertRaises(guard.DemoSeedGuardError):
            guard.check(sample)

    def test_unsafe_environment_and_ai_storage_scanner_fail(self):
        for key, value in (
            ("APP_ENV", "production"),
            ("APP_ENV", "staging"),
            ("APP_ENV", "development"),
            ("APP_ENV", ""),
            ("AI_PROVIDER", "openai"),
            ("AI_PROVIDER", ""),
            ("MALWARE_SCAN_ENABLED", "false"),
            ("MALWARE_SCAN_ENABLED", ""),
            ("STORAGE_BACKEND", "s3"),
            ("STORAGE_BACKEND", ""),
        ):
            sample = fixture()
            sample[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(
                guard.DemoSeedGuardError
            ):
                guard.check(sample)

    def test_remote_or_mismatched_database_fails_closed(self):
        for url in (
            "postgresql+psycopg://test_runner:secret@customer.example:5432/isolated_mcri_test",
            "postgresql+psycopg://test_runner:secret@127.0.0.1:5432/isolated_mcri_test",
            "postgresql+psycopg://test_runner:secret@db:6543/isolated_mcri_test",
            "postgresql+psycopg://other:secret@db:5432/isolated_mcri_test",
            "postgresql+psycopg://test_runner:secret@db:5432/customer_db",
            "postgresql+psycopg://test_runner@db:5432/isolated_mcri_test",
            "postgresql+psycopg://test_runner:secret@db:bad/isolated_mcri_test",
            "postgresql+psycopg://test_runner:secret@db:5432/isolated_mcri_test?sslmode=disable",
            "",
        ):
            sample = fixture()
            sample["DATABASE_URL"] = url
            with self.subTest(db=url.split("@")[-1]), self.assertRaises(
                guard.DemoSeedGuardError
            ):
                guard.check(sample)
        sample = fixture()
        sample["POSTGRES_DB"] = "customer_db"
        with self.assertRaises(guard.DemoSeedGuardError):
            guard.check(sample)

    def test_public_or_credential_bearing_api_target_fails(self):
        for value in (
            "https://public.example/api/v1",
            "http://customer.internal:8000/api/v1",
            "http://127.0.0.1:9000/api/v1",
            "http://127.0.0.1:8000/admin",
            "http://foo:bar@127.0.0.1:8000/api/v1",
            "http://127.0.0.1:8000/api/v1?token=private",
            "",
        ):
            sample = fixture()
            sample["NEXT_PUBLIC_API_BASE_URL"] = value
            with self.subTest(api=value.split("@")[-1]), self.assertRaises(
                guard.DemoSeedGuardError
            ):
                guard.check(sample)

    def test_cli_never_exposes_private_url_or_claim_data(self):
        sample = fixture()
        sample["DATABASE_URL"] = (
            "postgresql+psycopg://test_runner:VERY_PRIVATE_TOKEN"
            "@private.example:5432/customer_db"
        )
        output = io.StringIO()
        with patch.dict(guard.os.environ, sample, clear=True):
            with contextlib.redirect_stderr(output):
                self.assertEqual(guard.main(), 2)
        self.assertNotIn("VERY_PRIVATE_TOKEN", output.getvalue())
        self.assertNotIn("private.example", output.getvalue())
        self.assertNotIn("customer_db", output.getvalue())
        with patch.dict(guard.os.environ, fixture(), clear=True):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(guard.main(), 0)


if __name__ == "__main__":
    unittest.main()

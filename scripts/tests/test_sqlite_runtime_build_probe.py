"""Fail-closed regressions for the synthetic runtime build probe."""
import importlib.util
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import MagicMock, patch


SOURCE = Path(__file__).resolve().parents[2] / "apps/api/build_tools/verify_sqlite_runtime.py"
SPEC = importlib.util.spec_from_file_location("sqlite_build_probe", SOURCE)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class SQLiteBuildProbeTests(unittest.TestCase):
    def run_probe(self, *, features=("ENABLE_FTS5", "ENABLE_SESSION"),
                  unicode_ok=True, search_count=1):
        connection = MagicMock()
        def execute(sql, parameters=()):
            cursor = MagicMock()
            if sql == "PRAGMA compile_options":
                return iter((feature,) for feature in features)
            if sql == "INSERT INTO synthetic VALUES (?)":
                self.synthetic_value = parameters[0]
            if sql == "SELECT value FROM synthetic":
                cursor.fetchone.return_value = (self.synthetic_value if unicode_ok else "altered",)
            if "SELECT count(*)" in sql:
                cursor.fetchone.return_value = (search_count,)
            return cursor
        connection.execute.side_effect = execute
        manager = MagicMock()
        manager.__enter__.return_value = connection
        with patch.object(probe.sqlite3, "sqlite_version", probe.EXPECTED_VERSION), \
             patch.object(probe.sqlite3, "connect", return_value=manager) as connect, \
             patch.object(probe.shutil, "which", return_value=None):
            result = probe.verify()
        connect.assert_called_once_with(":memory:")
        manager.__exit__.assert_called_once()
        return result

    def test_success_is_compatibility_only_with_no_cli(self):
        result = self.run_probe()
        self.assertFalse(result["sqlite_cli_present"])
        self.assertTrue(result["synthetic_unicode_roundtrip"])
        self.assertIn("compatibility only", result["scope"])

    def test_wrong_version_rejects_before_connect(self):
        with patch.object(probe.sqlite3, "sqlite_version", "3.53.4"), \
             patch.object(probe.sqlite3, "connect") as connect:
            with self.assertRaisesRegex(RuntimeError, "version_mismatch"):
                probe.verify()
            connect.assert_not_called()

    def test_cli_present_rejects_before_connect(self):
        with patch.object(probe.sqlite3, "sqlite_version", probe.EXPECTED_VERSION), \
             patch.object(probe.shutil, "which", return_value="/usr/bin/sqlite3"), \
             patch.object(probe.sqlite3, "connect") as connect:
            with self.assertRaisesRegex(RuntimeError, "unexpected_sqlite_cli"):
                probe.verify()
            connect.assert_not_called()

    def test_each_required_feature_is_mandatory(self):
        for features in ((), ("ENABLE_FTS5",), ("ENABLE_SESSION",)):
            with self.subTest(features=features):
                with self.assertRaisesRegex(RuntimeError, "feature_regression"):
                    self.run_probe(features=features)

    def test_altered_unicode_rejects(self):
        with self.assertRaisesRegex(RuntimeError, "unicode_roundtrip_failed"):
            self.run_probe(unicode_ok=False)

    def test_incorrect_search_result_rejects(self):
        for count in (0, 2):
            with self.subTest(count=count):
                with self.assertRaisesRegex(RuntimeError, "fts5_probe_failed"):
                    self.run_probe(search_count=count)

    def test_database_error_is_not_swallowed(self):
        with patch.object(probe.sqlite3, "sqlite_version", probe.EXPECTED_VERSION), \
             patch.object(probe.shutil, "which", return_value=None), \
             patch.object(probe.sqlite3, "connect", side_effect=sqlite3.OperationalError("synthetic failure")):
            with self.assertRaises(sqlite3.OperationalError):
                probe.verify()


if __name__ == "__main__":
    unittest.main()

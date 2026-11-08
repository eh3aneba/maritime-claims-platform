"""Offline fail-closed contracts for the disposable Debian Slim diagnostic."""
import unittest

from scripts.probe_debian_slim_sqlite import IMAGE, ProbeError, report, validate


DIGEST = "sha256:" + "a" * 64
BASE = {
    "sqlite_version": "3.46.1",
    "debian_sqlite_package": "3.46.1-7+deb13u2",
    "sqlite_cli_present": False,
    "fts5_synthetic_ok": True,
}


class DebianSlimSqliteProbeTests(unittest.TestCase):
    def test_known_old_release_remains_no_go(self):
        value = report(dict(BASE), DIGEST)
        self.assertIn("NO-GO", value)
        self.assertIn("Below upstream 3.54.0", value)
        self.assertIn("not", value.lower())
        self.assertIn("all 11 checks", value)

    def test_newer_version_or_absent_cli_never_clears_security(self):
        value = report({**BASE, "sqlite_version": "3.54.1", "sqlite_cli_present": False}, DIGEST)
        self.assertIn("NO-GO", value)
        self.assertIn("CLI absence", value)
        self.assertIn("untested", value)

    def test_incomplete_corrupt_or_unverified_features_fail_closed(self):
        for data in (
            {},
            {**BASE, "bad": "injected"},
            {**BASE, "sqlite_version": "3.54.1<script>"},
            {**BASE, "debian_sqlite_package": ""},
            {**BASE, "sqlite_cli_present": "false"},
            {**BASE, "fts5_synthetic_ok": False},
        ):
            with self.subTest(data=data), self.assertRaises(ProbeError):
                validate(data)
        with self.assertRaises(ProbeError):
            report(dict(BASE), "unverified")

    def test_image_is_specific_supported_stable_candidate(self):
        self.assertEqual(IMAGE, "python:3.14.10-slim-trixie")


if __name__ == "__main__":
    unittest.main()

"""Read-only final-image SQLite evidence must never be treated as CVE clearance."""
from __future__ import annotations

from pathlib import Path
import unittest

from scripts.observe_production_sqlite_runtime import (
    ROLES, extract_package_version, get_evidence, sqlite_library_paths,
)

ROOT = Path(__file__).resolve().parents[2]


class SqliteRuntimeEvidenceContract(unittest.TestCase):
    def test_exact_installed_apk_version_only(self) -> None:
        self.assertEqual(
            extract_package_version("sqlite-libs-3.53.4-r0\n"), "3.53.4-r0"
        )
        for value in (
            "", "sqlite-3.53.4-r0", "sqlite-libs-3.53.4-r0\nother",
            "sqlite-libs-3.54.0-r0; unexpected", "sqlite-libs-no-version",
        ):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                extract_package_version(value)

    def test_actual_shared_library_mapping_required(self) -> None:
        self.assertEqual(
            sqlite_library_paths(
                "abc r-xp 0000 00:00 123 /usr/lib/libsqlite3.so.0.8.6\n"
                "def r--p 0000 00:00 123 /usr/lib/libsqlite3.so.0.8.6\n"
            ),
            ["/usr/lib/libsqlite3.so.0.8.6"],
        )
        with self.assertRaises(RuntimeError):
            sqlite_library_paths("abcdef r-xp 0000 00:00 12 /usr/lib/libz.so\n")

    def test_roles_reject_unknown_images_before_shelling_out(self) -> None:
        self.assertEqual(ROLES, {"api", "worker"})
        for role in ("", "web", "api;command", "producer"):
            with self.subTest(role=role), self.assertRaises(RuntimeError):
                get_evidence(role)

    def test_no_security_clearance_and_synthetic_only(self) -> None:
        source = (ROOT / "scripts" / "observe_production_sqlite_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"cve_clearance": False', source)
        self.assertIn('sqlite3.connect(":memory:")', source)
        self.assertIn("PRAGMA compile_options", source)
        self.assertIn("ENABLE_FTS5", source)
        self.assertIn("ENABLE_SESSION", source)
        self.assertIn('shutil.which("sqlite3")', source)
        self.assertIn('Path("/proc/self/maps")', source)
        self.assertNotIn("--allow-untrusted", source)

    def test_image_scan_runs_after_evidence_even_on_observer_failure(self) -> None:
        wf = (ROOT / ".github" / "workflows" / "supply-chain.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("id: sqlite-evidence", wf)
        self.assertIn("continue-on-error: true", wf)
        self.assertIn("SEECLAIMS_RUNTIME_ROLE=", wf)
        self.assertIn("scripts/observe_production_sqlite_runtime.py", wf)
        self.assertLess(wf.index("id: sqlite-evidence"), wf.index("name: Scan API image"))
        self.assertIn('test "${SQLITE_EVIDENCE_OUTCOME}" = "success"', wf)
        self.assertEqual(wf.count("severity-cutoff: high"), 3)
        self.assertEqual(wf.count("fail-build: true"), 3)
        self.assertEqual((ROOT / ".grype.yaml").read_text().strip(), "ignore: []")


if __name__ == "__main__":
    unittest.main()

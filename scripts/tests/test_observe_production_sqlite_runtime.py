"""Read-only final-image SQLite evidence must never be treated as CVE clearance."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

from scripts.observe_production_sqlite_runtime import (
    ROLES, extract_package_version, get_evidence, sqlite_library_paths,
    validate_runtime_provenance, nss_runtime_version,
)

ROOT = Path(__file__).resolve().parents[2]


class SqliteRuntimeEvidenceContract(unittest.TestCase):
    def test_exact_installed_apk_version_only(self) -> None:
        self.assertEqual(
            extract_package_version("sqlite-libs-3.53.4-r0\n"), "3.53.4-r0"
        )
        # A real apk info -v inventory contains many other installed
        # packages. Only the exact single sqlite-libs record is relevant.
        self.assertEqual(
            extract_package_version(
                "busybox-1.37.0-r1\nlibssl3-3.5.4-r0\n"
                "sqlite-libs-3.53.4-r0\nzlib-1.3.2-r1\n"
            ), "3.53.4-r0"
        )
        for value in (
            "", "sqlite-3.53.4-r0",
            "sqlite-libs-3.53.4-r0\nsqlite-libs-3.54.1-r0",
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

    def test_observer_process_rejects_hidden_extra_sqlite_mappings(self) -> None:
        # Exercise the actual observer entry point: valid APK/Python versions
        # must not hide another SQLite mapping with a deleted or spaced path.
        good = "1000-2000 r-xp 0000 00:00 123 /usr/lib/libsqlite3.so.3.53.4\n"
        cases = {
            "normal_segments": (good + good.replace("1000-2000", "3000-4000"), True),
            "deleted_old_library": (
                good + "3000-4000 r-xp 0000 00:00 456 /opt/libsqlite3.so.3.46.1 (deleted)\n",
                False,
            ),
            "deleted_same_version": (good + good.rstrip() + " (deleted)\n", False),
            "spaced_path": (
                good + "3000-4000 r-xp 0000 00:00 456 /opt/libsqlite3.so.3.46.1 backup\n",
                False,
            ),
        }
        for name, (maps, accepted) in cases.items():
            with self.subTest(name=name):
                code = textwrap.dedent('''
                    import os
                    from types import SimpleNamespace
                    from unittest.mock import patch
                    from scripts import observe_production_sqlite_runtime as observer

                    with patch.dict(os.environ, {"SEECLAIMS_RUNTIME_ROLE": "api"}), \\
                         patch.object(observer.subprocess, "run", return_value=SimpleNamespace(stdout="sqlite-libs-3.53.4-r0")), \\
                         patch.object(observer.sqlite3, "sqlite_version", "3.53.4"), \\
                         patch.object(observer.shutil, "which", return_value=None), \\
                         patch.object(observer.Path, "read_text", return_value=MAPS):
                        raise SystemExit(observer.main())
                ''').replace("MAPS", repr(maps))
                result = subprocess.run(
                    [sys.executable, "-c", code], cwd=ROOT,
                    text=True, capture_output=True, timeout=15,
                )
                if accepted:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('"cve_clearance": false', result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("Mapped SQLite library does not match", result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_runtime_provenance_is_fail_closed(self) -> None:
        evidence = {
            "sqlite_package_version": "3.53.4-r0",
            "python_sqlite_version": "3.53.4",
            "sqlite_cli_present": False,
            "mapped_sqlite_libraries": ["/usr/lib/libsqlite3.so.3.53.4"],
            "cve_clearance": False,
        }
        # A signed vendor backport can change revision without changing the
        # SQLite API's embedded semantic version. This is not CVE clearance.
        validate_runtime_provenance(evidence)
        validate_runtime_provenance({
            **evidence, "sqlite_package_version": "3.53.4-r1",
        })
        for change in (
            {"sqlite_package_version": "3.54.1-r0"},
            {"python_sqlite_version": "3.54.1"},
            {"sqlite_cli_present": True},
            {"mapped_sqlite_libraries": []},
            {"mapped_sqlite_libraries": ["/usr/lib/libsqlite3.so.3.54.1"]},
            {"mapped_sqlite_libraries": ["/opt/vendor/libsqlite3.so.3.53.4"]},
            {"mapped_sqlite_libraries": ["/usr/lib/libsqlite3.so.3.53.4 (deleted)"]},
            {"mapped_sqlite_libraries": ["/usr/lib/libsqlite3.so.3.53.4",
                                         "/usr/lib/libsqlite3.so.3.54.1"]},
            {"cve_clearance": True},
            {"sqlite_package_version": "3.54.1-r0; injected"},
        ):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                validate_runtime_provenance({**evidence, **change})

    def test_worker_nss_shared_library_linkage_is_required(self) -> None:
        class VersionFunction:
            restype = None

            def __init__(self, value: bytes | None) -> None:
                self.value = value

            def __call__(self) -> bytes | None:
                return self.value

        class FakeNss:
            def __init__(self, value: bytes | None) -> None:
                self.NSS_GetVersion = VersionFunction(value)

        with patch(
            "scripts.observe_production_sqlite_runtime.ctypes.CDLL",
            return_value=FakeNss(b"3.119.2"),
        ) as loader:
            self.assertEqual(nss_runtime_version(), "3.119.2")
            loader.assert_called_once_with("libnss3.so")
        for raw in (b"", None, b"invalid", b"3.119;injected"):
            with self.subTest(raw=raw), patch(
                "scripts.observe_production_sqlite_runtime.ctypes.CDLL",
                return_value=FakeNss(raw),
            ), self.assertRaises(RuntimeError):
                nss_runtime_version()

        evidence = {
            "role": "worker",
            "sqlite_package_version": "3.53.4-r0",
            "python_sqlite_version": "3.53.4",
            "sqlite_cli_present": False,
            "mapped_sqlite_libraries": ["/usr/lib/libsqlite3.so.3.53.4"],
            "cve_clearance": False,
        }
        with self.assertRaises(RuntimeError):
            validate_runtime_provenance(evidence)
        validate_runtime_provenance({**evidence, "worker_nss_version": "3.119.2"})

    def test_no_security_clearance_and_synthetic_only(self) -> None:
        source = (ROOT / "scripts" / "observe_production_sqlite_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('["/sbin/apk", "info", "-v"]', source)
        self.assertNotIn('["/sbin/apk", "info", "-v", "sqlite-libs"]', source)
        self.assertIn('"cve_clearance": False', source)
        self.assertIn('sqlite3.connect(":memory:")', source)
        self.assertIn("PRAGMA compile_options", source)
        self.assertIn("ENABLE_FTS5", source)
        self.assertIn("ENABLE_SESSION", source)
        self.assertIn('ctypes.CDLL("libnss3.so")', source)
        self.assertIn('if role == "worker" else None', source)
        self.assertIn('shutil.which("sqlite3")', source)
        self.assertIn('Path("/proc/self/maps")', source)
        self.assertIn('expected_library = "/usr/lib/libsqlite3.so." + match.group(1)', source)
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

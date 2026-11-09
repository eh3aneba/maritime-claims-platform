"""Offline tests; no network, Docker, APK installation, or customer evidence."""
from __future__ import annotations

import io
import tarfile
import unittest

from scripts.observe_alpine_stable_sqlite import (
    ALPINE_RELEASE,
    ARCHITECTURES,
    BASELINE_VERSION,
    ObservationError,
    extract_sqlite_lib_version,
    report_summary,
    sqlite_version_from_archive,
)


def _archive(text: str, *, duplicate: bool = False) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        for _ in range(2 if duplicate else 1):
            data = text.encode("utf-8")
            item = tarfile.TarInfo("APKINDEX")
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    return buf.getvalue()


class AlpineStableSQLiteObservationTests(unittest.TestCase):
    def test_exact_package_lookup_ignores_other_sqlite_names(self) -> None:
        data = "P:sqlite\nV:9.99.9-r9\n\nP:sqlite-libs\nV:3.53.4-r0\n\nP:libsqlite3\nV:99.0.0-r0\n"
        self.assertEqual(extract_sqlite_lib_version(data.encode()), BASELINE_VERSION)
        self.assertEqual(sqlite_version_from_archive(_archive(data)), BASELINE_VERSION)

    def test_duplicate_absent_or_invalid_version_fails_closed(self) -> None:
        cases = (
            "P:sqlite\nV:3.53.4-r0\n",
            "P:sqlite-libs\nV:3.53.4-r0\n\nP:sqlite-libs\nV:3.54.1-r0\n",
            "P:sqlite-libs\nV:3.53.4-r0\nV:3.54.1-r0\n",
            "P:sqlite-libs\nV:3.54.1-r0<script>\n",
        )
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ObservationError):
                extract_sqlite_lib_version(data.encode())
        with self.assertRaises(ObservationError):
            sqlite_version_from_archive(_archive("P:sqlite-libs\nV:3.53.4-r0\n", duplicate=True))
        with self.assertRaises(ObservationError):
            sqlite_version_from_archive(b"not a gzipped official index")

    def test_unchanged_packages_never_claim_remediation(self) -> None:
        results = [
            (a, f"https://dl-cdn.alpinelinux.org/alpine/{ALPINE_RELEASE}/main/{a}/APKINDEX.tar.gz", BASELINE_VERSION)
            for a in ARCHITECTURES
        ]
        summary, changed = report_summary(results)
        self.assertFalse(changed)
        self.assertIn("Existing four High CVEs remain a security hold", summary)
        self.assertNotIn("HUMAN SECURITY REVIEW REQUIRED", summary)

    def test_changed_package_requests_manual_review_not_cve_clearance(self) -> None:
        results = [
            (a, f"https://dl-cdn.alpinelinux.org/alpine/{ALPINE_RELEASE}/main/{a}/APKINDEX.tar.gz", "3.54.1-r1")
            for a in ARCHITECTURES
        ]
        summary, changed = report_summary(results)
        self.assertTrue(changed)
        self.assertIn("HUMAN SECURITY REVIEW REQUIRED", summary)
        self.assertIn("not a fix, scan result", summary)
        self.assertIn("mandatory API, Worker, Web Grype", summary)

    def test_no_partial_or_untrusted_architecture_in_report(self) -> None:
        url = f"https://dl-cdn.alpinelinux.org/alpine/{ALPINE_RELEASE}/main/x86_64/APKINDEX.tar.gz"
        for entries in (
            [("x86_64", url, BASELINE_VERSION)],
            [("x86_64", url, BASELINE_VERSION), ("oops", url, BASELINE_VERSION)],
            [("x86_64", "https://mirror.invalid/evil", BASELINE_VERSION), ("aarch64", url, BASELINE_VERSION)],
        ):
            with self.subTest(entries=entries), self.assertRaises(ObservationError):
                report_summary(entries)


if __name__ == "__main__":
    unittest.main()

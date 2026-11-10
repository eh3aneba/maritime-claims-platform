"""Fail-closed synthetic tests for the two official LibTIFF distribution paths.

Tests never access networks and cannot approve a different production digest.
They prove fallback is restricted to transport failures and approved hosts,
while publication requires the existing fixed SHA-512 byte-for-byte.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from apps.api.build_tools import fetch_pinned_libtiff as release


class OfficialLibtiffSourceTests(unittest.TestCase):
    def test_only_pinned_official_osgeo_sources_and_digest(self) -> None:
        self.assertEqual(
            release.URLS,
            (
                "https://download-cache.osgeo.org/libtiff/tiff-4.7.2.tar.gz",
                "https://download.osgeo.org/libtiff/tiff-4.7.2.tar.gz",
            ),
        )
        self.assertEqual(len(release.SHA512), 128)
        self.assertEqual(release.SHA512, (
            "bad66954a7e7e158c6dcbfc0e2d0032b8f3e2a354b6d0fdbb8038a7963e36c5"
            "b8a433dd4ee81c6c4dabfb50094152d440aa1f32b5299098c9ae29e55de2e41fc"
        ))
        self.assertEqual(release.MAX_ATTEMPTS_PER_SOURCE, 2)
        self.assertLessEqual(release.TIMEOUT_SECONDS, 60)
        self.assertEqual(
            {urlsplit(url).hostname for url in release.URLS},
            {"download-cache.osgeo.org", "download.osgeo.org"},
        )
        self.assertTrue(all(urlsplit(url).scheme == "https" for url in release.URLS))

    def test_valid_cache_bytes_publish_without_contacting_primary(self) -> None:
        synthetic = b"fixed-synthetic-osgeo-release"
        calls = []
        sleeps = []

        def opener(url, *, timeout):
            calls.append((url, timeout))
            return BytesIO(synthetic)

        with TemporaryDirectory() as home, patch.object(
            release, "SHA512", hashlib.sha512(synthetic).hexdigest(),
        ):
            output = Path(home) / "tiff.tar.gz"
            release.fetch(output, open_url=opener, sleep=sleeps.append)
            self.assertEqual(output.read_bytes(), synthetic)
            self.assertFalse((Path(home) / "tiff.tar.gz.unverified").exists())
            self.assertEqual(calls, [(release.URLS[0], release.TIMEOUT_SECONDS)])
            self.assertEqual(sleeps, [])

    def test_exhaust_cache_then_fetch_identical_pinned_primary(self) -> None:
        synthetic = b"same-synthetic-release-bytes"
        calls = []
        sleeps = []

        def opener(url, *, timeout):
            calls.append(url)
            if url == release.URLS[0]:
                raise OSError("synthetic cache transport outage")
            self.assertEqual(timeout, release.TIMEOUT_SECONDS)
            return BytesIO(synthetic)

        with TemporaryDirectory() as home, patch.object(
            release, "SHA512", hashlib.sha512(synthetic).hexdigest(),
        ):
            output = Path(home) / "tiff.tar.gz"
            release.fetch(output, open_url=opener, sleep=sleeps.append)
            self.assertEqual(output.read_bytes(), synthetic)
            self.assertEqual(calls, [
                release.URLS[0], release.URLS[0], release.URLS[1],
            ])
            self.assertEqual(sleeps, [2])

    def test_integrity_mismatch_never_falls_back_or_publishes(self) -> None:
        calls = []

        def opener(url, *, timeout):
            calls.append(url)
            return BytesIO(b"unapproved-changed-bytes")

        with TemporaryDirectory() as home:
            output = Path(home) / "tiff.tar.gz"
            output.write_bytes(b"stale-must-not-survive")
            with self.assertRaisesRegex(
                release.IntegrityMismatch, "pinned_libtiff_sha512_mismatch",
            ):
                release.fetch(output, open_url=opener, sleep=lambda _: None)
            self.assertEqual(calls, [release.URLS[0]])
            self.assertFalse(output.exists())
            self.assertFalse(output.with_name(output.name + ".unverified").exists())

    def test_exhaust_all_transport_attempts_without_publishing(self) -> None:
        calls = []
        sleeps = []

        def unavailable(url, *, timeout):
            calls.append(url)
            raise TimeoutError("synthetic timed-out official source")

        with TemporaryDirectory() as home:
            output = Path(home) / "tiff.tar.gz"
            output.write_bytes(b"stale")
            with self.assertRaisesRegex(
                release.DownloadUnavailable, "pinned_libtiff_download_unavailable",
            ):
                release.fetch(output, open_url=unavailable, sleep=sleeps.append)
            self.assertEqual(calls, [
                release.URLS[0], release.URLS[0],
                release.URLS[1], release.URLS[1],
            ])
            self.assertEqual(sleeps, [2, 2])
            self.assertFalse(output.exists())
            self.assertFalse(output.with_name(output.name + ".unverified").exists())

    def test_failure_to_publish_is_not_relabelled_as_download_outage(self) -> None:
        synthetic = b"test-artifact"
        with TemporaryDirectory() as home, patch.object(
            release, "SHA512", hashlib.sha512(synthetic).hexdigest(),
        ):
            output = Path(home) / "nonexistent" / "tiff.tar.gz"
            with self.assertRaises(FileNotFoundError):
                release.fetch(
                    output,
                    open_url=lambda url, *, timeout: BytesIO(synthetic),
                    sleep=lambda _: None,
                )


if __name__ == "__main__":
    unittest.main()

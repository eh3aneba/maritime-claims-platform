"""Keep the owner's production Edge rejection fail-closed and content-free."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.check_production_package_sources import validate_sources


SCRIPT = Path(__file__).resolve().parents[1] / "check_production_package_sources.py"


class ProductionPackageSourceTests(unittest.TestCase):
    def test_default_stable_source_is_allowed(self):
        validate_sources("FROM python:3.14.10-alpine3.24 AS base\nRUN apk add sqlite-libs\n")

    def test_explicit_stable_source_is_not_edge(self):
        validate_sources("FROM python:3.14.10-alpine3.24\nRUN apk add --repository https://dl-cdn.alpinelinux.org/alpine/v3.24/main sqlite-libs\n")

    def test_production_edge_literal_is_rejected(self):
        for suffix in ("/main", "/community", "", "?query=1"):
            with self.subTest(suffix=suffix):
                with self.assertRaisesRegex(ValueError, "edge_source_not_approved"):
                    validate_sources("FROM python:3.14.10-alpine3.24\nRUN apk add --repository https://dl-cdn.alpinelinux.org/alpine/edge" + suffix + " sqlite-libs\n")

    def test_split_and_encoded_edge_literals_are_rejected(self):
        for path in ("ed\\\nge/main", "%65dge/main", "EDGE/main"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "edge_source_not_approved"):
                    validate_sources("FROM python:3.14.10-alpine3.24\nRUN apk add --repository https://dl-cdn.alpinelinux.org/alpine/" + path + " sqlite-libs\n")

    def test_comment_does_not_activate_repository(self):
        validate_sources("# Reject https://dl-cdn.alpinelinux.org/alpine/edge/main\nFROM python:3.14.10-alpine3.24\n")

    def test_invalid_or_unsupported_input_rejects(self):
        for source in ("", "# no build instructions", "FROM python\x00", "# escape=`\nFROM python\n"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    validate_sources(source)

    def test_cli_policy_rejection_has_nonzero_exit_without_source_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Dockerfile"
            path.write_text("FROM python\nRUN apk add --repository https://example.invalid/alpine/edge/main synthetic-private-marker\n")
            result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr.strip(), "production_alpine_edge_source_not_approved")
            self.assertNotIn("synthetic-private-marker", result.stdout + result.stderr)

    def test_cli_missing_file_rejects_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(SCRIPT), str(Path(directory) / "missing")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr.strip(), "production_dockerfile_unreadable")

    def test_cli_corrupt_encoding_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Dockerfile"
            path.write_bytes(b"FROM python\n\xff")
            result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr.strip(), "production_dockerfile_unreadable")

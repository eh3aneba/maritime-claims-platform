"""Offline synthetic checks for strict pre-restore PostgreSQL metadata handling.

No Docker Engine, real database, customer file or restore is invoked.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "verify_postgres_backup.sh"

FAKE_DOCKER = r"""#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" != "compose exec -T db pg_restore --list" ]]; then
  echo "Unexpected synthetic docker request" >&2
  exit 44
fi
cat >/dev/null
"""


class BackupMetadataVerifyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        bindir = self.root / "bin"
        bindir.mkdir()
        fake = bindir / "docker"
        fake.write_text(FAKE_DOCKER, encoding="utf-8")
        fake.chmod(0o700)
        self.env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"]}
        self.dump = self.root / "synthetic-pilot.dump"
        self.dump.write_bytes(b"PGDMP synthetic archive only; not a real claim or database")
        digest = hashlib.sha256(self.dump.read_bytes()).hexdigest()
        self.sha = Path(str(self.dump) + ".sha256")
        self.sha.write_text(f"{digest}  {self.dump.name}\n", encoding="utf-8")
        self.meta = Path(str(self.dump) + ".meta")
        self.lines = [
            "format=mcri-postgres-backup-v1",
            "created_at_utc=2026-11-17T03:00:00Z",
            "database=synthetic_pilot",
            "git_sha=" + "a" * 40,
            "alembic_heads=0224_obs_refresh_recovery_anchor",
            "dump_file=" + self.dump.name,
            "dump_sha256=" + digest,
        ]
        self.write_metadata(self.lines)

    def write_metadata(self, lines):
        self.meta.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def verify(self):
        return subprocess.run(
            ["bash", str(SCRIPT), str(self.dump)],
            env=self.env, text=True, capture_output=True, check=False,
            timeout=10,
        )

    def test_valid_writer_metadata_is_verified(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Backup verification passed", result.stdout)

    def test_second_duplicate_key_cannot_be_silently_ignored(self):
        for injected in ("database=synthetic_pilot", "database=other_database",
                         "dump_sha256=" + "b" * 64):
            with self.subTest(injected=injected.split("=")[0]):
                self.write_metadata([*self.lines, injected])
                result = self.verify()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Duplicate backup metadata field", result.stderr)

    def test_missing_or_unknown_field_is_rejected(self):
        cases = (
            [line for line in self.lines if not line.startswith("git_sha=")],
            [*self.lines, "future_unreviewed_authority=pass"],
            [*self.lines, "malformed_without_equals"],
            [*self.lines, ""],
        )
        for entries in cases:
            with self.subTest(entries=len(entries), last=entries[-1]):
                self.write_metadata(entries)
                result = self.verify()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("metadata", result.stderr.lower())

    def test_symlink_for_dump_or_either_sidecar_is_rejected(self):
        for original in (self.dump, self.sha, self.meta):
            with self.subTest(name=original.name):
                data = original.read_bytes()
                target = self.root / ("owned-" + original.name)
                target.write_bytes(data)
                original.unlink()
                try:
                    original.symlink_to(target)
                except (OSError, NotImplementedError):
                    self.skipTest("symlinks are unavailable")
                try:
                    self.assertNotEqual(self.verify().returncode, 0)
                finally:
                    original.unlink()
                    original.write_bytes(data)
                self.assertEqual(target.read_bytes(), data)

    def test_corrupt_dump_still_fails_checksum_before_archive_probe(self):
        self.dump.write_bytes(b"tampered synthetic dump")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()

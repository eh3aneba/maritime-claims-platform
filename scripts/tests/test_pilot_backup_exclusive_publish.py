"""Offline no-Docker regression for exclusive, atomic backup artifact publication.

The shell runs under a temporary fake Docker CLI. No customer data, real DB or
real Docker Engine is touched.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "backup_postgres.sh"
FAKE_DOCKER = r'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MOCK_BACKUP_LOG"
case "$*" in
  "compose exec -T db psql "*)
    printf '0224_obs_refresh_recovery_anchor\n'
    ;;
  "compose exec -T db pg_dump "*)
    printf 'PGDMP-fixture-only-test-no-real-data\n'
    if [[ -n "$MOCK_COLLISION" ]]; then
      # Deliberately create the competing file while dump generation is
      # underway: the first no-clobber precheck has already completed.
      printf '%s' "raced-external-owned-file" > "$MOCK_COLLISION"
    fi
    ;;
  "compose exec -T db pg_restore --list")
    if [[ "$MOCK_FAIL_ARCHIVE" == "1" ]]; then
      exit 33
    fi
    cat >/dev/null
    ;;
  *)
    echo "Unexpected fake Docker invocation" >&2
    exit 44
    ;;
esac
'''


class BackupExclusivePublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        bindir = root / "bin"
        bindir.mkdir()
        fake = bindir / "docker"
        fake.write_text(FAKE_DOCKER, encoding="utf-8")
        fake.chmod(0o700)
        self.root = root
        self.output = root / "space in name.dump"
        self.log = root / "docker.log"
        self.env = {
            **os.environ,
            "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
            "MOCK_BACKUP_LOG": str(self.log),
            "POSTGRES_USER": "only-test-user",
            "POSTGRES_DB": "only_test_database",
        }

    def execute(self, *, collision=None, fail_archive=False):
        env = dict(self.env)
        env["MOCK_COLLISION"] = str(collision) if collision else ""
        env["MOCK_FAIL_ARCHIVE"] = "1" if fail_archive else "0"
        return subprocess.run(
            ["bash", str(SCRIPT), str(self.output)], env=env,
            cwd=self.root, capture_output=True, text=True, timeout=20,
            check=False,
        )

    def assert_no_partials(self):
        self.assertFalse(list(self.root.glob("*.partial.*")))

    def test_happy_path_creates_three_valid_artifacts_exclusively(self):
        run = self.execute()
        self.assertEqual(run.returncode, 0, run.stderr)
        dump = self.output.read_bytes()
        digest = hashlib.sha256(dump).hexdigest()
        self.assertEqual(
            Path(str(self.output) + ".sha256").read_text(),
            f"{digest}  {self.output.name}\n",
        )
        metadata = Path(str(self.output) + ".meta").read_text()
        self.assertIn(f"dump_sha256={digest}\n", metadata)
        self.assertIn(f"database=only_test_database\n", metadata)
        self.assertIn("alembic_heads=0224_obs_refresh_recovery_anchor\n", metadata)
        self.assert_no_partials()
        self.assertEqual(self.execute().returncode, 1)
        self.assertEqual(self.output.read_bytes(), dump)

    def test_late_collision_cannot_overwrite_any_final_destination(self):
        for suffix in ("", ".sha256", ".meta"):
            with self.subTest(suffix=suffix):
                target = Path(str(self.output) + suffix)
                self.log.unlink(missing_ok=True)
                for path in (self.output,
                             Path(str(self.output) + ".sha256"),
                             Path(str(self.output) + ".meta")):
                    path.unlink(missing_ok=True)
                run = self.execute(collision=target)
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual(target.read_text(), "raced-external-owned-file")
                for sibling in (self.output,
                                Path(str(self.output) + ".sha256"),
                                Path(str(self.output) + ".meta")):
                    if sibling != target:
                        self.assertFalse(sibling.exists())
                self.assert_no_partials()
                self.assertIn("pg_dump", self.log.read_text())

    def test_preexisting_artifact_or_symlink_cannot_be_overwritten(self):
        for suffix in ("", ".meta", ".sha256"):
            with self.subTest(suffix=suffix):
                target = Path(str(self.output) + suffix)
                target.write_text("existing")
                self.log.unlink(missing_ok=True)
                run = self.execute()
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual(target.read_text(), "existing")
                self.assertFalse(self.log.exists())
                target.unlink()
        victim = self.root / "owned-by-others.txt"
        victim.write_text("untouched")
        self.output.symlink_to(victim)
        self.assertNotEqual(self.execute().returncode, 0)
        self.assertEqual(victim.read_text(), "untouched")
        self.assertTrue(self.output.is_symlink())

    def test_archive_validation_failure_removes_all_private_temporaries(self):
        result = self.execute(fail_archive=True)
        self.assertNotEqual(result.returncode, 0)
        for path in (self.output, Path(str(self.output) + ".sha256"),
                     Path(str(self.output) + ".meta")):
            self.assertFalse(path.exists())
        self.assert_no_partials()


if __name__ == "__main__":
    unittest.main()

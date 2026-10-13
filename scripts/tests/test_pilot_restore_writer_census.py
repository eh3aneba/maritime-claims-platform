"""Offline regression: destructive restore must fail closed on Docker ps errors.

All Docker operations are redirected to a temporary fake executable. These
tests NEVER connect to a Docker daemon, drop a real database or touch Evidence.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "restore_postgres.sh"
FAKE_DOCKER = r'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MOCK_DOCKER_LOG"
if [[ "$*" == *"psql -v ON_ERROR_STOP=1"* ]]; then
  n="$(cat "$MOCK_DB_SESSION_COUNTER")"
  n=$((n + 1))
  printf '%s\n' "$n" > "$MOCK_DB_SESSION_COUNTER"
  if [[ "$MOCK_DOCKER_SCENARIO" == "session-error-first" && "$n" == 1 ]] ||
     [[ "$MOCK_DOCKER_SCENARIO" == "session-error-last" && "$n" == 2 ]]; then
    printf 'private database connection details must not leak\n' >&2
    exit 42
  fi
  if [[ "$MOCK_DOCKER_SCENARIO" == "foreign-session-first" && "$n" == 1 ]] ||
     [[ "$MOCK_DOCKER_SCENARIO" == "foreign-session-last" && "$n" == 2 ]]; then
    printf '1\n'
    exit 0
  fi
  if [[ "$MOCK_DOCKER_SCENARIO" == "invalid-session-census" ]]; then
    printf 'private-host-identity\n'
    exit 0
  fi
  printf '0\n'
  exit 0
fi
if [[ "$*" == "compose ps --status running --services" ]]; then
  n="$(cat "$MOCK_DOCKER_COUNTER")"
  n=$((n + 1))
  printf '%s\n' "$n" > "$MOCK_DOCKER_COUNTER"
  if [[ "$MOCK_DOCKER_SCENARIO" == "fail-first" && "$n" == 1 ]] ||
     [[ "$MOCK_DOCKER_SCENARIO" == "fail-second" && "$n" == 2 ]] ||
     [[ "$MOCK_DOCKER_SCENARIO" == "fail-third" && "$n" == 3 ]]; then
    printf 'secret-customer-data-must-not-leak\n' >&2
    exit 17
  fi
  if [[ "$MOCK_DOCKER_SCENARIO" == "unexpected" ]]; then
    printf 'db\nunapproved-writer\n'
    exit 0
  fi
  if [[ "$MOCK_DOCKER_SCENARIO" == "empty-second" && "$n" == 2 ]]; then
    exit 0
  fi
  printf 'db\n'
  exit 0
fi
exit 0
'''


class RestoreWriterCensusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        bindir = root / "bin"
        bindir.mkdir()
        binary = bindir / "docker"
        binary.write_text(FAKE_DOCKER, encoding="utf-8")
        binary.chmod(0o700)
        self.log = root / "docker.log"
        self.counter = root / "counter"
        self.counter.write_text("0")
        self.session_counter = root / "db-session-counter"
        self.session_counter.write_text("0")
        dump = root / "synthetic.dump"
        dump.write_bytes(b"PGDMP-only-a-mock-test-fixture")
        digest = hashlib.sha256(dump.read_bytes()).hexdigest()
        Path(str(dump) + ".sha256").write_text(f"{digest}  {dump.name}\n")
        Path(str(dump) + ".meta").write_text(
            f"format=mcri-postgres-backup-v1\n"
            "created_at_utc=2026-10-13T00:00:00Z\n"
            "database=mcri_restore_unit_test\n"
            "git_sha=" + "a" * 40 + "\n"
            "alembic_heads=0003\n"
            f"dump_file={dump.name}\n"
            f"dump_sha256={digest}\n"
        )
        self.dump = dump
        self.env = dict(os.environ)
        self.env.update({
            "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
            "MOCK_DOCKER_LOG": str(self.log),
            "MOCK_DOCKER_COUNTER": str(self.counter),
            "MOCK_DB_SESSION_COUNTER": str(self.session_counter),
            "APP_ENV": "test",
            "POSTGRES_USER": "mcri_test",
            "POSTGRES_DB": "mcri_restore_unit_test",
            "MCRI_RESTORE_CONFIRM": "YES",
            "MCRI_RESTORE_PAIR_MANIFEST": "",
            "MCRI_RESTORE_EVIDENCE_ARCHIVE": "",
            "MCRI_RESTORE_RELEASE_SHA": "",
        })

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, scenario):
        env = dict(self.env, MOCK_DOCKER_SCENARIO=scenario)
        run = subprocess.run(
            ["bash", str(SCRIPT), str(self.dump)],
            env=env, cwd=self.temp.name, check=False,
            capture_output=True, text=True, timeout=30,
        )
        return run, self.log.read_text() if self.log.exists() else ""

    def test_docker_ps_failure_never_means_zero_writers(self):
        for scenario in ("fail-first", "fail-second", "fail-third"):
            with self.subTest(scenario=scenario):
                self.counter.write_text("0")
                self.log.write_text("")
                result, trace = self.execute(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cannot verify running Compose services", result.stderr)
                self.assertNotIn("secret-customer-data", result.stderr)
                self.assertNotIn("dropdb", trace)
                self.assertNotIn("createdb", trace)
                self.assertNotIn("run --rm migrate", trace)
                self.assertEqual(int(self.counter.read_text()), {
                    "fail-first": 1, "fail-second": 2, "fail-third": 3,
                }[scenario])

    def test_unknown_writer_prevents_any_destructive_operation(self):
        result, trace = self.execute("unexpected")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unapproved Compose writer", result.stderr)
        self.assertNotIn("unapproved-writer", result.stderr)
        self.assertNotIn("dropdb", trace)

    def test_database_must_still_be_running_before_restore(self):
        result, trace = self.execute("empty-second")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PostgreSQL is no longer", result.stderr)
        self.assertNotIn("dropdb", trace)

    def test_foreign_database_session_blocks_dropdb_even_with_no_compose_writers(self):
        for scenario in ("foreign-session-first", "foreign-session-last"):
            with self.subTest(scenario=scenario):
                self.counter.write_text("0")
                self.session_counter.write_text("0")
                self.log.write_text("")
                result, trace = self.execute(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("active sessions or invalid session census", result.stderr)
                self.assertNotIn("dropdb", trace)
                self.assertNotIn("createdb", trace)
                self.assertEqual(int(self.session_counter.read_text()),
                                 1 if scenario.endswith("first") else 2)

    def test_sql_census_errors_and_untrusted_text_fail_closed(self):
        for scenario in ("session-error-first", "session-error-last",
                         "invalid-session-census"):
            with self.subTest(scenario=scenario):
                self.counter.write_text("0")
                self.session_counter.write_text("0")
                self.log.write_text("")
                result, trace = self.execute(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Refusing restore:", result.stderr)
                self.assertNotIn("private database", result.stderr)
                self.assertNotIn("private-host-identity", result.stderr)
                self.assertNotIn("dropdb", trace)
                self.assertNotIn("createdb", trace)

    def test_mock_success_census_runs_three_times_prior_to_dropdb(self):
        result, trace = self.execute("safe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.counter.read_text().strip(), "3")
        self.assertEqual(self.session_counter.read_text().strip(), "2")
        self.assertIn("FROM pg_stat_activity", trace)
        self.assertIn("pid <> pg_backend_pid()", trace)
        self.assertIn("-d mcri_restore_unit_test", trace)
        self.assertIn("dropdb", trace)
        drop_command = next(line for line in trace.splitlines() if "dropdb" in line)
        self.assertIn("--if-exists", drop_command)
        self.assertNotIn("--force", drop_command)
        self.assertLess(trace.index("compose ps --status running --services"), trace.index("dropdb"))
        self.assertIn("pg_restore --list", trace)


if __name__ == "__main__":
    unittest.main()

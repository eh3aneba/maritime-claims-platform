"""No-network regression checks for the synthetic CI recovery probe.

Mock-only tests. A real backup/clone can pass ONLY in the isolated Docker CI job.
"""
from pathlib import Path
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ci_restore_probe as p  # noqa: E402

SHA = "a" * 40
ENV = {
    "APP_ENV": "test",
    "MCRI_CI_RESTORE_PROBE": "1",
    "POSTGRES_DB": "mcri_performance",
    "POSTGRES_USER": "mcri_performance",
}


class RecoveryProbeTests(unittest.TestCase):
    def test_refuses_non_synthetic_or_wrong_compose_environment(self):
        for bad_file, bad_env in (
            (".env", ENV),
            (".env.performance", {**ENV, "APP_ENV": "pilot"}),
            (".env.performance", {**ENV, "MCRI_CI_RESTORE_PROBE": "0"}),
            (".env.performance", {**ENV, "POSTGRES_DB": "maritime_claims"}),
            (".env.performance", {**ENV, "POSTGRES_USER": "maritime"}),
        ):
            with self.assertRaises(p.ProbeError):
                p.validate_guard(bad_file, bad_env)
        p.validate_guard(".env.performance", ENV)

    def _simulate(self, *, break_at: str = ""):
        calls = []

        def command(cmd, *, env, stdin_file=None, timeout=180):
            calls.append(cmd)
            if cmd == ["git", "rev-parse", "HEAD"]:
                return SHA
            if cmd == p._compose(".env.performance", "ps", "--status",
                                 "running", "--services"):
                if break_at == "unexpected_running":
                    return "db\nclamav\nworker"
                return "db\nclamav"
            if "psql" in cmd:
                if "COUNT(*)" in cmd[-1]:
                    return "1"
                if "json_agg" in cmd[-1]:
                    return '[{"key":"synthetic/item.pdf","sha256":"' + "a" * 64 + '","size":4}]'
                return "0224_obs_refresh_recovery_anchor"
            if "backup_postgres.sh" in " ".join(cmd):
                Path(cmd[-1]).write_bytes(b"PGDMP-synthetic")
            if "createdb" in cmd and break_at == "createdb":
                raise p.ProbeError("createdb refused")
            if "pg_restore" in cmd and break_at == "restore":
                raise p.ProbeError("clone restore refused")
            return ""

        def archive(cmd, *, stdout, **kwargs):
            self.assertIn("run", cmd)
            self.assertIn("--no-deps", cmd)
            self.assertIn("--rm", cmd)
            self.assertIn("api", cmd)
            self.assertNotIn("exec", cmd)
            stdout.write(b"synthetic-test-archive")
            return subprocess.CompletedProcess(cmd, 0, stdout=None, stderr=None)

        with patch.object(p, "_run", side_effect=command), \
             patch.object(p.subprocess, "run", side_effect=archive), \
             patch.object(p, "restore_and_reconcile", return_value={
                 "files_restored": 2, "demo_documents_matched": 1,
             }):
            if break_at:
                with self.assertRaises(p.ProbeError):
                    p.observe(env_file=".env.performance", env=ENV)
                return calls, None
            return calls, p.observe(env_file=".env.performance", env=ENV)

    def test_synthetic_restore_does_not_change_active_database(self):
        commands, record = self._simulate()
        self.assertTrue(record["isolated_db_clone_restored"])
        self.assertTrue(record["evidence_archive_integrity_bound"])
        self.assertTrue(record["compose_writer_quiescence_verified"])
        self.assertFalse(record["external_writer_quiescence_verified"])
        self.assertEqual(record["isolated_evidence_files_restored"], 2)
        self.assertEqual(record["restored_demo_document_hashes_matched"], 1)
        self.assertFalse(record["matched_recovery_point_verified"])
        self.assertFalse(record["evidence_restore_verified"])
        self.assertFalse(record["full_restore_drill_verified"])
        self.assertFalse(record["pilot_authorized"])
        self.assertFalse(record["active_application_db_restored_or_dropped"])
        self.assertTrue(any("createdb" in x for x in commands))
        self.assertTrue(any("dropdb" in x for x in commands))
        stop_index = next(i for i, x in enumerate(commands) if "stop" in x)
        ps_index = next(i for i, x in enumerate(commands) if "ps" in x)
        backup_index = next(i for i, x in enumerate(commands)
                            if "backup_postgres.sh" in " ".join(x))
        self.assertLess(stop_index, ps_index)
        self.assertLess(ps_index, backup_index)
        self.assertFalse(any("restore_postgres.sh" in x for x in commands))
        database_mutations = [x for x in commands
                              if "createdb" in x or "dropdb" in x or "pg_restore" in x]
        self.assertTrue(all(p.CLONE_DB in x for x in database_mutations))
        self.assertNotIn("synthetic-test-archive", json.dumps(record))

    def test_quiescence_failure_aborts_before_any_backup_or_clone(self):
        commands, _ = self._simulate(break_at="unexpected_running")
        self.assertTrue(any("stop" in x for x in commands))
        self.assertFalse(any("backup_postgres.sh" in x for x in commands))
        self.assertFalse(any("createdb" in x for x in commands))
        self.assertFalse(any("dropdb" in x for x in commands))

    def test_quiescence_requires_only_two_known_services(self):
        with patch.object(p, "_run", side_effect=[
            "", "db\nclamav\nunknown-service",
        ]):
            with self.assertRaises(p.ProbeError):
                p.quiesce_compose_writers(".env.performance", ENV)

    def test_createdb_failure_never_drops_someone_elses_database(self):
        commands, _ = self._simulate(break_at="createdb")
        self.assertTrue(any("createdb" in x for x in commands))
        self.assertFalse(any("dropdb" in x for x in commands))

    def test_clone_restore_failure_still_cleans_up_isolated_db(self):
        commands, _ = self._simulate(break_at="restore")
        self.assertTrue(any("createdb" in x for x in commands))
        self.assertTrue(any("dropdb" in x for x in commands))
        self.assertFalse(any("restore_postgres.sh" in x for x in commands))

    def test_errors_do_not_expose_raw_subprocess_output(self):
        result = subprocess.CompletedProcess(["docker"], 1,
                                             stdout="synthetic secret claim",
                                             stderr="private-credential")
        with patch.object(p.subprocess, "run", return_value=result):
            with self.assertRaises(p.ProbeError) as ctx:
                p._run(["docker", "compose", "ps"], env=ENV)
        self.assertNotIn("private-credential", str(ctx.exception))
        self.assertNotIn("synthetic secret claim", str(ctx.exception))

    def test_cli_fail_closed_outside_test_environment(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "probe.json"
            with patch.dict(p.os.environ, {"APP_ENV": "production"}, clear=True):
                with contextlib.redirect_stderr(io.StringIO()):
                    result = p.main(["--env-file", ".env.performance", "--output",
                                     str(out)])
            self.assertEqual(result, 2)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()

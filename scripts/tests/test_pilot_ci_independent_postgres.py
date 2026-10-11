"""Offline tests for second, network-disconnected PostgreSQL recovery boundary."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ci_independent_postgres as p  # noqa: E402
from pilot_ci_lineage_reconcile import collect_lineage

SHA = "a" * 40
ENV = {
    "APP_ENV": "test",
    "MCRI_CI_RESTORE_PROBE": "1",
    "POSTGRES_DB": "mcri_performance",
    "POSTGRES_USER": "mcri_performance",
    "POSTGRES_PASSWORD": "".join(("synthetic", "-", "ci", "-", "never", "-", "real")),
}
ROW = '[{"id":"00000000-0000-0000-0000-000000000001","marker":"synthetic"}]'


class IndependentPostgresTests(unittest.TestCase):
    def _exercise(self, *, break_at=""):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "synthetic.dump"
            archive = Path(tmp) / "synthetic.tar"
            dump.write_bytes(b"PGDMP-synthetic-placeholder")
            archive.write_bytes(b"synthetic-tar-placeholder")
            source = collect_lineage("source", lambda _, sql: ROW)

            def command(args, *, stdin_file=None, timeout=120):
                calls.append(args)
                if args[:2] == ["docker", "run"] and break_at == "start":
                    raise p.IndependentRestoreError("start failed")
                if "pg_restore" in args and break_at == "restore":
                    raise p.IndependentRestoreError("restore failed")
                if "pg_isready" in args and break_at == "ready":
                    raise p.IndependentRestoreError("not ready")
                return "success"

            def query(name, sql):
                self.assertEqual(name, "mcri-ci-independent-" + SHA[:16])
                if "COUNT(*)" in sql:
                    return "1"
                if "alembic_version" in sql:
                    return "0224_obs_refresh_recovery_anchor"
                if "jsonb_agg" in sql:
                    if break_at == "lineage":
                        return '[{"id":"00000000-0000-0000-0000-000000000001","marker":"changed"}]'
                    return ROW
                if "json_agg" in sql:
                    return '[{"key":"synthetic.pdf","sha256":"' + "a" * 64 + '","size":4}]'
                raise AssertionError("unexpected fixed SQL query")

            with patch.object(p, "_run", side_effect=command), \
                 patch.object(p, "_query", side_effect=query), \
                 patch.object(p, "restore_and_reconcile", return_value={
                     "files_restored": 1, "demo_documents_matched": 1,
                 }), \
                 patch.object(p.time, "sleep"):
                kwargs = dict(dump=dump, archive=archive, release_sha=SHA,
                              expected_claim_count="1",
                              expected_revision="0224_obs_refresh_recovery_anchor",
                              source_lineage=source, env=ENV)
                if break_at:
                    with self.assertRaises(p.IndependentRestoreError):
                        p.restore_and_verify(**kwargs)
                    return calls, None
                result = p.restore_and_verify(**kwargs)
            return calls, result

    def test_success_is_a_distinct_engine_with_network_disabled(self):
        calls, result = self._exercise()
        run = next(x for x in calls if x[:2] == ["docker", "run"])
        self.assertIn("--network", run)
        self.assertEqual(run[run.index("--network") + 1], "none")
        self.assertEqual(run[-1], p.POSTGRES_IMAGE)
        self.assertIn("--env-file", run)
        self.assertNotIn(ENV["POSTGRES_PASSWORD"], " ".join(run))
        self.assertEqual(result["separate_engine_lineage_families_matched"], 7)
        self.assertEqual(result["separate_engine_documents_matched"], 1)
        self.assertFalse(result["real_fresh_host_recovery_verified"])
        self.assertFalse(result["pilot_authorized"])
        self.assertTrue(any("pg_restore" in command for command in calls))
        self.assertEqual(calls[-1], [
            "docker", "rm", "-f", "-v",
            "mcri-ci-independent-" + SHA[:16],
        ])

    def test_restore_and_lineage_failures_cleanup_own_container(self):
        for failure in ("restore", "lineage", "ready"):
            with self.subTest(failure=failure):
                calls, result = self._exercise(break_at=failure)
                self.assertIsNone(result)
                self.assertEqual(calls[-1][0:4], ["docker", "rm", "-f", "-v"])

    def test_failed_container_start_must_not_remove_existing_container(self):
        calls, _ = self._exercise(break_at="start")
        self.assertFalse(any(x[:3] == ["docker", "rm", "-f"] for x in calls))

    def test_prod_guard_refuses_all_docker_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            dump = Path(d) / "a.dump"
            archive = Path(d) / "b.tar"
            dump.write_bytes(b"synthetic-data")
            archive.write_bytes(b"synthetic-data")
            for env in (
                {**ENV, "APP_ENV": "production"},
                {**ENV, "POSTGRES_DB": "customer-db"},
                {**ENV, "MCRI_CI_RESTORE_PROBE": "0"},
                {**ENV, "POSTGRES_PASSWORD": "short"},
                {**ENV, "POSTGRES_PASSWORD": "contains\\nline"},
            ):
                with patch.object(p, "_run") as process:
                    with self.assertRaises(p.IndependentRestoreError):
                        p.restore_and_verify(
                            dump=dump, archive=archive, release_sha=SHA,
                            expected_claim_count="1", expected_revision="0224_test",
                            source_lineage={}, env=env)
                    process.assert_not_called()

    def test_private_docker_failure_text_never_escapes(self):
        completed = subprocess.CompletedProcess(
            ["docker"], 17, stdout="secret-claim-body",
            stderr="private-postgres-credentials")
        with patch.object(p.subprocess, "run", return_value=completed):
            with self.assertRaises(p.IndependentRestoreError) as caught:
                p._run(["docker", "ps"])
        self.assertNotIn("private-postgres-credentials", str(caught.exception))
        self.assertNotIn("secret-claim-body", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

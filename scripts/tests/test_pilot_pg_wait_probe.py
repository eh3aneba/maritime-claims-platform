"""Network-free safety regressions for Pilot PostgreSQL CI wait observer."""
from pathlib import Path
import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_pg_wait_probe as probe  # noqa: E402


_CI_ENV = {
    "APP_ENV": "test",
    "EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST": "1",
    "MCRI_TEST_DATABASE_URL":
        "postgresql+psycopg://ci:secret@127.0.0.1:5432/mcri_concurrency_ci",
}


class PilotPgWaitProbeTests(unittest.TestCase):
    def test_guard_allows_only_synthetic_local_postgresql_ci(self):
        with patch.dict(os.environ, _CI_ENV, clear=True):
            self.assertTrue(probe._ci_database_url().startswith("postgresql://"))
        for overrides in (
            {"APP_ENV": "production"},
            {"EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST": "0"},
            {"MCRI_TEST_DATABASE_URL":
             "postgresql+psycopg://ci:secret@prod.invalid:5432/mcri_concurrency_ci"},
            {"MCRI_TEST_DATABASE_URL":
             "postgresql+psycopg://ci:secret@127.0.0.1:5432/customer_claims"},
        ):
            with patch.dict(os.environ, {**_CI_ENV, **overrides}, clear=True):
                with self.assertRaises(ValueError):
                    probe._ci_database_url()

    def test_safe_summary_is_query_free_and_bounded(self):
        rows = [
            (101, "active", "Lock", "transactionid", 123, [102]),
            (102, "idle in transaction", "Client", "ClientRead", 12345, []),
            (103, "contains-secret-state", None, None, 0, None),
        ]
        result = probe.safe_summary(rows)
        self.assertEqual(result["client_count"], 3)
        self.assertEqual(result["blocked_count"], 1)
        self.assertEqual(result["sessions"][0]["blocking_pids"], [102])
        self.assertEqual(result["sessions"][2]["state"], "other")
        for forbidden in ("query", "password", "secret", "username", "connection"):
            self.assertNotIn(forbidden, json.dumps(result).lower())
        self.assertEqual(len(probe.safe_summary(rows * 20)["sessions"]), 32)

    def test_one_way_wait_is_not_mistaken_for_observed_deadlock_cycle(self):
        result = probe.safe_summary([
            (201, "active", "Lock", "transactionid", 9, [202]),
            (202, "idle in transaction", "Client", "ClientRead", 10, []),
            (203, "idle", "Client", "ClientRead", 0, []),
        ])
        self.assertEqual(result["blocked_count"], 1)
        self.assertFalse(result["observed_blocker_cycle_in_sample"])
        self.assertTrue(result["sample_blocker_graph_complete"])

    def test_two_and_three_session_cycles_are_observed_but_not_certified(self):
        for edges in (
            [(201, [202]), (202, [201])],
            [(201, [202]), (202, [203]), (203, [201])],
        ):
            with self.subTest(edges=edges):
                rows = [
                    (pid, "active", "Lock", "transactionid", 5, blockers)
                    for pid, blockers in edges
                ]
                result = probe.safe_summary(rows)
                self.assertTrue(result["observed_blocker_cycle_in_sample"])
                self.assertTrue(result["sample_blocker_graph_complete"])
                self.assertEqual(result["blocked_count"], len(rows))
                self.assertNotIn("deadlock_confirmed", result)

    def test_external_or_truncated_blocker_graph_is_marked_incomplete(self):
        external = probe.safe_summary([
            (201, "active", "Lock", "transactionid", 5, [999]),
        ])
        self.assertFalse(external["observed_blocker_cycle_in_sample"])
        self.assertFalse(external["sample_blocker_graph_complete"])
        self.assertEqual(external["sessions"][0]["blocking_pids"], [999])

        rows = [
            (i, "active", "Lock", "transactionid", 5, [i + 1])
            for i in range(100, 133)
        ]
        capped = probe.safe_summary(rows)
        self.assertEqual(capped["client_count"], 32)
        self.assertTrue(capped["truncated"])
        self.assertFalse(capped["sample_blocker_graph_complete"])
        self.assertFalse(capped["observed_blocker_cycle_in_sample"])

    def test_more_than_sixteen_blockers_never_claims_complete_graph(self):
        # All blocker sessions fit within the 32-row sample, but the
        # per-session output clips PID lists to 16. Before this fix, the
        # sampled graph incorrectly reported complete coverage.
        blocker_ids = list(range(301, 318))
        rows = [
            (201, "active", "Lock", "transactionid", 5, blocker_ids),
            *((pid, "idle in transaction", "Client", "ClientRead", 10, [])
              for pid in blocker_ids),
        ]
        report = probe.safe_summary(rows)
        self.assertFalse(report["truncated"])
        self.assertTrue(report["blocker_pid_lists_truncated"])
        self.assertEqual(report["client_count"], 18)
        self.assertEqual(len(report["sessions"][0]["blocking_pids"]), 16)
        self.assertEqual(report["blocked_count"], 1)
        self.assertFalse(report["sample_blocker_graph_complete"])
        self.assertFalse(report["observed_blocker_cycle_in_sample"])

    def test_complete_bounded_blocker_list_remains_accurate(self):
        rows = [
            (201, "active", "Lock", "transactionid", 5, [202]),
            (202, "idle in transaction", "Client", "ClientRead", 10, []),
        ]
        report = probe.safe_summary(rows)
        self.assertFalse(report["blocker_pid_lists_truncated"])
        self.assertTrue(report["sample_blocker_graph_complete"])

    def test_observer_graph_cannot_echo_any_query_text(self):
        rows = [
            (201, "active", "Lock", "transactionid", 3, [202]),
            (202, "idle in transaction", "Client", "ClientRead", 5, []),
        ]
        payload = json.dumps(probe.safe_summary(rows))
        for forbidden in ("SELECT", "private_claim", "customer", "credential",
                          "password", "SQL statement", "secret"):
            self.assertNotIn(forbidden, payload)
        self.assertNotIn("query", payload.lower())

    def test_failed_sample_does_not_print_exception_secrets(self):
        out = io.StringIO()
        with (patch.dict(os.environ, _CI_ENV, clear=True),
              patch.object(probe.time, "sleep"),
              patch.object(probe, "observe_once",
                           side_effect=RuntimeError("postgresql://ci:secret@db.invalid")),
              contextlib.redirect_stdout(out)):
            self.assertEqual(probe.main(["--interval-seconds", "60",
                                         "--max-samples", "1"]), 0)
        record = json.loads(out.getvalue())
        self.assertEqual(record["event"], "pg_wait_probe_error")
        self.assertEqual(record["exception_type"], "RuntimeError")
        self.assertNotIn("secret", out.getvalue())
        self.assertNotIn("db.invalid", out.getvalue())

    def test_runner_resources_use_only_fixed_kernel_counters_and_mounts(self):
        safe_ints = {
            "/sys/fs/cgroup/memory.current": 1024,
            "/sys/fs/cgroup/memory.peak": 2048,
            "/sys/fs/cgroup/memory.max": None,
        }
        safe_mounts = {"/tmp": 4096, "/dev/shm": 512}
        with (patch.dict(os.environ, _CI_ENV, clear=True),
              patch.object(probe, "_bounded_kernel_integer",
                           side_effect=lambda path: safe_ints[path]),
              patch.object(probe, "_cgroup_memory_events",
                           return_value={"oom": 2, "oom_kill": 0}),
              patch.object(probe, "_fixed_mount_available",
                           side_effect=lambda path: safe_mounts[path]),
              patch.object(probe, "_fixed_host_meminfo_bytes",
                           return_value={"host_mem_available_bytes": 16384,
                                         "host_mem_total_bytes": 32768})):
            report = probe.safe_ci_runner_resources()
        self.assertEqual(report["cgroup_memory_current_bytes"], 1024)
        self.assertEqual(report["cgroup_memory_peak_bytes"], 2048)
        self.assertIsNone(report["cgroup_memory_limit_bytes"])
        self.assertEqual(report["cgroup_oom_events"], 2)
        self.assertEqual(report["cgroup_oom_kill_events"], 0)
        self.assertEqual(report["tmp_available_bytes"], 4096)
        self.assertEqual(report["shm_available_bytes"], 512)
        self.assertEqual(report["host_mem_available_bytes"], 16384)
        self.assertEqual(report["host_mem_total_bytes"], 32768)
        self.assertEqual(len(report), 9)
        self.assertTrue(all(value is None or type(value) is int
                            for value in report.values()))
        for secret in ("password", "secret", "connection", "claim", "path"):
            self.assertNotIn(secret, json.dumps(report).lower())

    def test_resource_snapshot_rejects_non_ci_or_remote_database(self):
        with patch.dict(os.environ, {**_CI_ENV, "APP_ENV": "production"},
                        clear=True):
            with self.assertRaises(ValueError):
                probe.safe_ci_runner_resources()
        with patch.dict(os.environ, {
            **_CI_ENV,
            "MCRI_TEST_DATABASE_URL": "postgresql://ci:secret@prod.invalid/customer",
        }, clear=True):
            with self.assertRaises(ValueError):
                probe.safe_ci_runner_resources()

    def test_resource_probe_uses_null_when_kernel_counters_unavailable(self):
        with patch.dict(os.environ, _CI_ENV, clear=True):
            with patch.object(probe, "_bounded_kernel_integer", return_value=None), \
                 patch.object(probe, "_cgroup_memory_events",
                              return_value={"oom": None, "oom_kill": None}), \
                 patch.object(probe, "_fixed_mount_available", return_value=None), \
                 patch.object(probe, "_fixed_host_meminfo_bytes",
                              return_value={"host_mem_available_bytes": None,
                                            "host_mem_total_bytes": None}):
                report = probe.safe_ci_runner_resources()
        self.assertTrue(all(value is None for value in report.values()))

    def test_host_meminfo_fixed_fields_are_bounded_and_numeric(self):
        content = (
            "MemTotal:       8192 kB\\n"
            "MemAvailable:   4096 kB\\n"
            "SecretCustomerKey: 9999 kB\\n"
            "MemFree:        1 kB\\n"
        )
        with patch("builtins.open", mock_open(read_data=content)) as opened:
            report = probe._fixed_host_meminfo_bytes()
        opened.assert_called_once_with("/proc/meminfo", "r", encoding="ascii")
        self.assertEqual(report, {
            "host_mem_available_bytes": 4096 * 1024,
            "host_mem_total_bytes": 8192 * 1024,
        })
        self.assertNotIn("customer", json.dumps(report).lower())

    def test_host_meminfo_rejects_invalid_values_and_missing_proc(self):
        for payload in ("MemAvailable: -12 kB\\nMemTotal: 30 MB\\n",
                        "MemAvailable: 10\tMB\\nMemTotal: nope kB\\n",
                        "X" * 4096):
            with patch("builtins.open", mock_open(read_data=payload)):
                self.assertEqual(probe._fixed_host_meminfo_bytes(), {
                    "host_mem_available_bytes": None,
                    "host_mem_total_bytes": None,
                })
        with patch("builtins.open", side_effect=OSError):
            self.assertEqual(probe._fixed_host_meminfo_bytes(), {
                "host_mem_available_bytes": None,
                "host_mem_total_bytes": None,
            })

    def test_observer_interval_is_bounded_below_existing_job_deadline(self):
        with (patch.dict(os.environ, _CI_ENV, clear=True),
              contextlib.redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit):
                probe.main(["--interval-seconds", "300", "--max-samples", "45"])
            with self.assertRaises(SystemExit):
                probe.main(["--interval-seconds", "30", "--max-samples", "46"])

    def test_due_tick_workflow_uses_bounded_finer_probe_not_relaxed_tests(self):
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/postgres-concurrency-regressions.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "python -u ../../scripts/pilot_pg_wait_probe.py "
            "--interval-seconds 30 --max-samples 45 &",
            workflow,
        )
        self.assertIn("trap cleanup_probe EXIT", workflow)
        self.assertIn("faulthandler_timeout=180", workflow)
        self.assertIn("pytest_exit=$?", workflow)
        self.assertIn('exit "$pytest_exit"', workflow)
        self.assertIn("name: PostgreSQL concurrency gate", workflow)

    def test_guard_failure_does_not_display_uri(self):
        out = io.StringIO()
        with patch.dict(os.environ, {"APP_ENV": "production",
                                     "MCRI_TEST_DATABASE_URL": _CI_ENV["MCRI_TEST_DATABASE_URL"]},
                        clear=True), contextlib.redirect_stdout(out):
            self.assertEqual(probe.main(["--max-samples", "1"]), 2)
        self.assertIn("guard_failed", out.getvalue())
        self.assertNotIn("secret", out.getvalue())


if __name__ == "__main__":
    unittest.main()

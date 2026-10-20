"""Network-free safety regressions for Pilot PostgreSQL CI wait observer."""
from pathlib import Path
import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

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

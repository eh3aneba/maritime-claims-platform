"""Fail-closed test-only Backend CI scope regression tests."""
from __future__ import annotations
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from scripts import ci_backend_narrow_scope as scope

ROOT = Path(__file__).resolve().parents[2]
A = "apps/api/tests/test_local_ai_hm_loopback_smoke.py"
B = "apps/api/tests/test_local_ai_hm_fixture_matrix.py"
C = "apps/api/tests/test_local_ai_hm_repeat_smoke.py"
PG = "apps/api/tests/test_payment_settlement_concurrency_postgres.py"


class NarrowBackendCIRegressionTests(unittest.TestCase):
    def test_exact_three_audited_modules_only(self):
        for p in (A, B, C):
            with self.subTest(p=p):
                self.assertTrue(scope.is_db_free_synthetic_test(p))
                self.assertEqual(scope.classify([("M", p)]),
                                 ("narrow", ("tests/" + p.rsplit("/", 1)[1],)))
        mode, paths = scope.classify([("M", A), ("M", B), ("M", C)])
        self.assertEqual(mode, "narrow")
        self.assertEqual(set(paths), {"tests/test_local_ai_hm_loopback_smoke.py",
                                    "tests/test_local_ai_hm_fixture_matrix.py",
                                    "tests/test_local_ai_hm_repeat_smoke.py"})

    def test_unknown_and_mixed_changes_never_use_narrow(self):
        examples = (
            [("D", A)], [("A", A)], [("D", C)], [("A", C)], [("M", A), ("M", PG)],
            [("M", A), ("M", "docs/readme.md")],
            [("M", A), ("M", "scripts/tool.py")],
            [("M", "apps/api/app/core/preflight.py")],
            [("M", "apps/api/tests/conftest.py")],
            [("M", "apps/api/tests/db_harness.py")],
            [("M", "apps/api/requirements-dev.lock")],
            [("M", ".github/workflows/backend-premerge.yml")],
            [("M", "scripts/ci_backend_narrow_scope.py")],
            [("M", "scripts/ci_postgres_synthetic_test_scope.py")],
            [("R100", A)],
            [],
        )
        for example in examples:
            with self.subTest(example=example):
                self.assertEqual(scope.classify(example), ("full", ()))

    def test_ast_guard_failure_forces_full(self):
        with patch.object(scope, "is_db_free_synthetic_test", return_value=False):
            self.assertEqual(scope.classify([("M", A)]), ("full", ()))

    def test_legacy_pg_exceptions_remain_in_dedicated_workflow(self):
        self.assertEqual(scope.classify([("M", PG)]), ("none", ()))
        self.assertEqual(scope.classify([("M", scope.PG_WORKFLOW)]), ("none", ()))
        self.assertEqual(scope.classify([("M", "docs/readme.md")]), ("none", ()))

    def test_git_diff_missing_failed_or_ambiguous_is_full(self):
        for data in (b"", b"M\0" + A.encode(), b"M\0",
                     b"R100\0" + A.encode() + b"\0"):
            with self.subTest(data=data):
                try:
                    parsed = scope.parse_git_diff(data)
                except ValueError:
                    continue
                self.assertEqual(scope.classify(parsed), ("full", ()))
        sha1, sha2 = "a" * 40, "b" * 40
        with patch.object(scope.subprocess, "run", return_value=subprocess.CompletedProcess(
            args=["git"], returncode=1, stdout=b"", stderr=b"PRIVATE"
        )):
            with redirect_stdout(StringIO()) as stdout:
                self.assertEqual(scope.main([sha1, sha2]), 0)
            self.assertIn("backend_required=true", stdout.getvalue())
            self.assertNotIn("PRIVATE", stdout.getvalue())

    def test_full_backend_aggregate_remains_required_and_fail_closed(self):
        wf = (ROOT / ".github/workflows/backend-premerge.yml").read_text(encoding="utf-8")
        for marker in (
            "name: Backend tests", "name: Backend changed-test verification",
            "needs.backend-narrow.result", "CLASSIFIER_RESULT",
            "pytest --collect-only -q tests", "backend_required=true",
            "narrow_required=false", "python -m scripts.ci_backend_narrow_scope",
            "All 64 Backend shards passed.", "shard: [0, 1, 2, 3, 4, 5",
            "tests/test_local_ai_hm_repeat_smoke.py",
        ):
            self.assertIn(marker, wf)


if __name__ == "__main__":
    unittest.main()

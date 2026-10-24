"""Regression tests for fail-closed Docker/browser E2E scope admission."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts import ci_browser_offline_hm_scope as scope

REPO = Path(__file__).resolve().parents[2]
A, B, C = sorted(scope._ELIGIBLE)
BASE, HEAD = "a" * 40, "b" * 40


class OfflineHMBrowserScopeTests(unittest.TestCase):
    def test_only_three_independently_audited_modules_qualify(self):
        self.assertEqual(len(scope._ELIGIBLE), 3)
        for module in (A, B, C):
            with self.subTest(module=module):
                self.assertTrue(scope.is_db_free_synthetic_test(module))
                self.assertTrue(scope.eligible([("M", module)]))
        self.assertTrue(scope.eligible([("M", A), ("M", B), ("M", C)]))

    def test_unknown_mixed_deleted_added_renamed_duplicate_fail_closed(self):
        cases = [
            [], [("M", A), ("M", "docs/README.md")],
            [("M", A), ("M", "apps/api/app/main.py")],
            [("M", A), ("M", "apps/web/package.json")],
            [("M", A), ("M", ".github/workflows/ci.yml")],
            [("M", A), ("M", "scripts/ci_browser_offline_hm_scope.py")],
            [("M", A), ("M", "apps/api/tests/conftest.py")],
            [("M", A), ("M", "apps/api/requirements-dev.lock")],
            [("D", A)], [("A", A)], [("T", A)], [("R100", A)],
            [("M", A), ("M", A)],
            [("M", A), ("M", B), ("M", C), ("M", "docs/extra.md")],
            [("M", "../" + A)], [("M", A.upper())],
        ]
        for sample in cases:
            with self.subTest(sample=sample):
                self.assertFalse(scope.eligible(sample))

    def test_ast_guard_regression_forces_full_browser_run(self):
        with patch.object(scope, "is_db_free_synthetic_test", return_value=False):
            self.assertFalse(scope.eligible([("M", A)]))

    def test_exact_commit_nul_diff_and_bad_git_output_fail_closed(self):
        ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"M\0" + A.encode() + b"\0",
        )
        with patch.object(scope.subprocess, "run", return_value=ok) as run:
            self.assertTrue(scope.should_skip(BASE, HEAD))
        self.assertEqual(run.call_args.args[0], [
            "git", "diff", "--name-status", "--no-renames", "-z", BASE, HEAD,
        ])
        for data in (b"", b"M\0", b"M\0" + A.encode(),
                     b"M\0" + A.encode() + b"\0D\0apps/api/app/main.py\0"):
            with self.subTest(data=data), patch.object(
                scope.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 0, stdout=data),
            ):
                self.assertFalse(scope.should_skip(BASE, HEAD))

    def test_invalid_shas_git_failures_and_untrusted_error_never_skip(self):
        for invalid in (("", HEAD), (BASE, BASE), ("A" * 40, HEAD),
                        ("f" * 39, HEAD), (None, HEAD)):
            with self.subTest(pair=invalid):
                self.assertFalse(scope.should_skip(*invalid))
        with patch.object(scope.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 1, stdout=b"M\0" + A.encode() + b"\0", stderr=b"private output"
        )):
            self.assertFalse(scope.should_skip(BASE, HEAD))
        with patch.object(scope.subprocess, "run", side_effect=OSError("private secret")):
            with redirect_stdout(StringIO()) as out:
                self.assertEqual(scope.main([BASE, HEAD]), 0)
            self.assertEqual(out.getvalue(), "full\n")
            self.assertNotIn("secret", out.getvalue())

    def test_output_is_exact_skip_or_full_and_workflow_keeps_gate(self):
        with patch.object(scope, "should_skip", return_value=True):
            with redirect_stdout(StringIO()) as out:
                self.assertEqual(scope.main([BASE, HEAD]), 0)
            self.assertEqual(out.getvalue(), "skip\n")
        for args in ([], [BASE], [BASE, HEAD, "extra"]):
            with redirect_stdout(StringIO()) as out:
                self.assertEqual(scope.main(args), 0)
            self.assertEqual(out.getvalue(), "full\n")
        wf = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for must in (
            "name: Scoped CI gate",
            "require_selected_job",
            'require_selected_job "$E2E_REQUIRED" "$E2E_RESULT"',
            "name: Design partner browser E2E",
            "python -m scripts.ci_browser_offline_hm_scope",
            "python -m unittest scripts.tests.test_ci_browser_offline_hm_scope -v",
            'if [ "$EVENT_NAME" = "workflow_dispatch" ]; then',
            "e2e_required=true",
        ):
            self.assertIn(must, wf)


if __name__ == "__main__":
    unittest.main()

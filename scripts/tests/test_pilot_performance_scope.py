"""Unit regressions for fail-closed, selective live Docker smoke classification."""
from pathlib import Path
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_performance_scope as scope  # noqa: E402

BASE = "a" * 40
HEAD = "b" * 40


class PerformanceScopeTests(unittest.TestCase):
    def test_offline_evidence_record_changes_skip_expensive_live_stack(self):
        for path in scope.OFFLINE_SCRIPTS:
            with self.subTest(path=path):
                self.assertFalse(scope.requires_live_stack([path]))
        self.assertFalse(scope.requires_live_stack([
            "docs/operations/BACKUP_RESTORE.md",
            "scripts/pilot_rollback_rehearsal.py",
            "scripts/tests/test_pilot_rollback_rehearsal.py",
        ]))

    def test_known_static_docs_skip_and_live_changes_do_not(self):
        self.assertFalse(scope.requires_live_stack(["README.md"]))
        for path in (
            "apps/api/app/main.py",
            "apps/api/alembic/versions/0225_synthetic.py",
            "apps/web/package.json",
            "docker-compose.yml",
            "docker-compose.production.yml",
            ".github/workflows/performance-smoke.yml",
            ".github/workflows/backend-premerge.yml",
            "scripts/pilot_ci_restore_probe.py",
            "scripts/pilot_ci_resume_probe.py",
            "scripts/pilot_recovery_pair.py",
            "scripts/tests/test_pilot_ci_restore_probe.py",
            "scripts/design_partner_preflight.sh",
            "scripts/pilot_performance_scope.py",
            "scripts/new_unclassified_pilot_operator_tool.py",
            "pyproject.toml",
            ".env.pilot.example",
            "infra/private-proxy.conf",
        ):
            with self.subTest(path=path):
                self.assertTrue(scope.requires_live_stack([path]))

    def test_mixed_changes_and_invalid_paths_fail_closed(self):
        self.assertTrue(scope.requires_live_stack([
            "scripts/pilot_rc_gate.py", "scripts/pilot_ci_restore_probe.py"]))
        for bad in ([], [""], [None], ["../unsafe"], ["/root"], ["a\nb"],
                    ["docs/help.md", "apps/api/app/main.py"], ["a\x00b"]):
            with self.subTest(paths=bad):
                self.assertTrue(scope.requires_live_stack(bad))

    def test_exact_sha_diff_is_null_delimited_and_rename_safe(self):
        changed = b"docs/operations/BACKUP_RESTORE.md\x00scripts/pilot_rc_gate.py\x00"
        with patch.object(scope.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 0, stdout=changed)) as run:
            paths = scope.changed_files(BASE, HEAD)
        self.assertEqual(paths, [
            "docs/operations/BACKUP_RESTORE.md", "scripts/pilot_rc_gate.py"])
        self.assertEqual(
            run.call_args.args[0],
            ["git", "diff", "--name-only", "-z", "--no-renames", BASE, HEAD])
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_missing_or_failed_git_data_never_generates_false_skip(self):
        with self.assertRaises(scope.ScopeError):
            scope.changed_files(BASE, BASE)
        with self.assertRaises(scope.ScopeError):
            scope.changed_files("bad", HEAD)
        for result in (
            subprocess.CompletedProcess([], 1, stdout=b""),
            subprocess.CompletedProcess([], 0, stdout=b""),
            subprocess.CompletedProcess([], 0, stdout=b"\xff\x00"),
        ):
            with patch.object(scope.subprocess, "run", return_value=result):
                with self.assertRaises(scope.ScopeError):
                    scope.changed_files(BASE, HEAD)

    def test_cli_writes_stable_required_flag_and_fails_closed_on_git_issue(self):
        with tempfile.TemporaryDirectory() as dir:
            path = Path(dir) / "GITHUB_OUTPUT"
            with patch.object(scope, "changed_files",
                              return_value=["scripts/pilot_rc_gate.py"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(scope.main([
                        "--base", BASE, "--head", HEAD, "--output", str(path)]), 0)
            self.assertEqual(path.read_text(), "performance_required=false\n")
            with patch.object(scope, "changed_files", side_effect=scope.ScopeError("hidden")):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(scope.main([
                        "--base", BASE, "--head", HEAD, "--output", str(path)]), 0)
            self.assertEqual(path.read_text(),
                             "performance_required=false\nperformance_required=true\n")

    def test_unwritable_output_does_not_pass_classifier(self):
        with tempfile.TemporaryDirectory() as dir:
            path = Path(dir) / "nonexistent" / "GITHUB_OUTPUT"
            with patch.object(scope, "changed_files", return_value=["README.md"]), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(scope.main([
                    "--base", BASE, "--head", HEAD, "--output", str(path)]), 2)


if __name__ == "__main__":
    unittest.main()

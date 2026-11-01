"""Execute the real PostgreSQL scope/gate shell against unavailable exact diffs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/postgres-concurrency-regressions.yml"


def scope_shell() -> str:
    block = WORKFLOW.read_text().split(
        "      - name: Classify exact-head PostgreSQL concurrency scope\n", 1
    )[1].split("  postgres-concurrency:\n", 1)[0]
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


class PostgresExactDiffTests(unittest.TestCase):
    def classify(self, paths=(), *, git_exit=0, event="pull_request", base="a" * 40):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_git = root / "git"
            fake_git.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['GIT_CALLED']).touch()\n"
                "paths = json.loads(os.environ['DIFF_PATHS'])\n"
                "sep = b'\\0' if '-z' in sys.argv else b'\\n'\n"
                "sys.stdout.buffer.write(b''.join(p.encode() + sep for p in paths))\n"
                "raise SystemExit(int(os.environ['DIFF_EXIT']))\n"
            )
            fake_git.chmod(0o755)
            output = root / "outputs"
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                   "EVENT_NAME": event, "BASE_SHA": base, "HEAD_SHA": "b" * 40,
                   "GITHUB_OUTPUT": str(output), "DIFF_PATHS": json.dumps(paths),
                   "DIFF_EXIT": str(git_exit), "GIT_CALLED": str(root / "called")}
            result = subprocess.run(["bash", "-c", scope_shell()], env=env,
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            records = [line.split("=", 1) for line in output.read_text().splitlines()]
            self.assertEqual(len(records), 2)
            values = dict(records)
            values["groups"] = json.loads(values["groups"])
            return values, (root / "called").exists()

    def assert_full(self, result):
        values, _ = result
        self.assertEqual(values["postgres_required"], "true")
        expected = json.loads(re.search(r"all_groups='([^']+)'", scope_shell())[1])
        self.assertEqual(values["groups"], expected)
        self.assertEqual(len(set(values["groups"])), 17)

    def test_failed_git_diff_cannot_report_scope_not_required(self):
        self.assert_full(self.classify(git_exit=128))

    def test_partial_failed_diff_cannot_narrow_validation(self):
        self.assert_full(self.classify(
            ["apps/api/tests/test_payment_settlement_concurrency_postgres.py"], git_exit=1
        ))

    def test_empty_diff_is_ambiguous_and_requires_all_groups(self):
        self.assert_full(self.classify())

    def test_manual_and_missing_metadata_do_not_depend_on_git(self):
        for kwargs in ({"event": "workflow_dispatch"}, {"base": ""}):
            with self.subTest(kwargs=kwargs):
                result = self.classify(git_exit=128, **kwargs)
                self.assert_full(result)
                self.assertFalse(result[1])

    def test_runtime_shared_and_newline_paths_require_full_coverage(self):
        for path in ("apps/api/app/core/security.py", "apps/api/tests/conftest.py",
                     "apps/api/requirements-dev.lock", "apps/api/new\nsource.py",
                     ".github/workflows/postgres-concurrency-regressions.yml"):
            with self.subTest(path=path):
                self.assert_full(self.classify([path]))

    def test_known_test_changes_preserve_existing_group_union(self):
        values, _ = self.classify([
            "apps/api/tests/test_external_document_source_due_tick_dispatch_concurrency_postgres.py",
            "apps/api/tests/test_external_document_source_observation_review_decision_concurrency_postgres.py",
            "apps/api/tests/test_external_document_source_due_tick_dispatch_concurrency_postgres.py",
        ])
        self.assertEqual(values, {"postgres_required": "true",
                                  "groups": ["scheduling", "review-core"]})

    def test_successfully_observed_docs_diff_keeps_existing_skip(self):
        values, called = self.classify(["docs/synthetic guide.md"])
        self.assertTrue(called)
        self.assertEqual(values, {"postgres_required": "false", "groups": ["scheduling"]})

    def test_audited_offline_test_and_mixed_runtime_change(self):
        audited = "apps/api/tests/test_local_ai_hm_loopback_smoke.py"
        values, _ = self.classify([audited])
        self.assertEqual(values["postgres_required"], "false")
        self.assert_full(self.classify([audited, "apps/api/app/main.py"]))

    def test_matrix_and_required_gate_remain_fail_closed(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("name: PostgreSQL concurrency gate", workflow)
        self.assertIn("fail-fast: false", workflow)
        self.assertIn("python -m unittest scripts.tests.test_ci_postgres_diff_fail_closed -v", workflow)
        gate = workflow.split("  postgres-concurrency-gate:\n", 1)[1]
        shell = textwrap.dedent(gate.split("        run: |\n", 1)[1])
        base = {**os.environ, "CLASSIFIER_RESULT": "success", "POSTGRES_REQUIRED": "true",
                "POSTGRES_RESULT": "success"}
        for key in ("CLASSIFIER_RESULT", "POSTGRES_RESULT"):
            for status in ("failure", "cancelled", "skipped", ""):
                with self.subTest(key=key, status=status):
                    result = subprocess.run(["bash", "-c", shell], env={**base, key: status},
                                            capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
        self.assertEqual(subprocess.run(["bash", "-c", shell], env=base,
                                        capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()

"""Regression tests for exact-path offline AI-only PostgreSQL CI scope."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import ci_postgres_synthetic_test_scope as guard

REPO = Path(__file__).resolve().parents[2]
LOOPBACK = "apps/api/tests/test_local_ai_hm_loopback_smoke.py"
MATRIX = "apps/api/tests/test_local_ai_hm_fixture_matrix.py"


class OfflineAISyntheticPostgresScopeTests(unittest.TestCase):
    def test_current_code_owned_tests_are_allowed(self):
        for name in (LOOPBACK, MATRIX):
            with self.subTest(name=name):
                self.assertTrue(guard.is_db_free_synthetic_test(name))
                self.assertEqual(guard.main([name]), 0)

    def test_unknown_or_ambiguous_paths_are_fail_closed(self):
        for name in (
            "", None, False, 123, ".", "../outside.py",
            "apps/api/tests/test_payment_settlement_concurrency_postgres.py",
            "apps/api/app/ai/gateway/ollama_local.py",
            "scripts/ci_postgres_synthetic_test_scope.py",
            LOOPBACK + "/child", LOOPBACK.upper(),
        ):
            with self.subTest(name=name):
                self.assertFalse(guard.is_db_free_synthetic_test(name))
        self.assertEqual(guard.main([]), 1)
        self.assertEqual(guard.main([LOOPBACK, MATRIX]), 1)

    def test_unrecognized_import_and_db_operations_trigger_full_matrix(self):
        samples = [
            "import sqlalchemy\n",
            "from sqlalchemy.orm import Session\n",
            "import importlib\n",
            "from app.db import get_db\n",
            "from tests.db_harness import TestingSessionLocal\n",
            "import pytest\nDATABASE_URL = 'postgresql://dummy'\n",
            "import pytest\nsomething.execute('SELECT 1')\n",
            "import pytest\nexec('pass')\n",
            "import pytest\nopen('some-file')\n",
            "import pytest\n__import__('sqlalchemy')\n",
            "import pytest\nimportlib.import_module('sqlalchemy')\n",
            "def invalid(:\n",
        ]
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / LOOPBACK
            target.parent.mkdir(parents=True)
            for sample in samples:
                with self.subTest(sample=sample):
                    target.write_text(sample, encoding="utf-8")
                    with patch.object(guard, "_ROOT", Path(root)):
                        self.assertFalse(guard.is_db_free_synthetic_test(LOOPBACK))
            target.unlink()
            with patch.object(guard, "_ROOT", Path(root)):
                self.assertFalse(guard.is_db_free_synthetic_test(LOOPBACK))

    def test_audited_imports_not_implicitly_any_test(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / MATRIX
            target.parent.mkdir(parents=True)
            target.write_text("import pytest\nfrom pathlib import Path\n", encoding="utf-8")
            with patch.object(guard, "_ROOT", Path(root)):
                self.assertTrue(guard.is_db_free_synthetic_test(MATRIX))
            target.write_text("from app.modules.external_document_sources.service import helper\n", encoding="utf-8")
            with patch.object(guard, "_ROOT", Path(root)):
                self.assertFalse(guard.is_db_free_synthetic_test(MATRIX))

    def test_workflow_retains_exact_paths_and_fail_closed_gate(self):
        workflow = (REPO / ".github/workflows/postgres-concurrency-regressions.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "apps/api/tests/test_local_ai_hm_loopback_smoke.py|"
            "apps/api/tests/test_local_ai_hm_fixture_matrix.py)",
            workflow,
        )
        self.assertIn(
            'python3 scripts/ci_postgres_synthetic_test_scope.py "$path"',
            workflow,
        )
        self.assertIn(
            ".github/workflows/postgres-*.yml|"
            "scripts/ci_postgres_synthetic_test_scope.py|apps/api/*)",
            workflow,
        )
        self.assertIn('if [ "$POSTGRES_REQUIRED" = "true" ]; then', workflow)
        self.assertIn('echo "PostgreSQL concurrency gate passed."', workflow)


if __name__ == "__main__":
    unittest.main()

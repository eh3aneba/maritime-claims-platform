"""Always-on policy contract for code-owned offline H&M scenario matrix."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "scripts/pilot_local_ai_hm_fixture_matrix.py"
TESTS = ROOT / "apps/api/tests/test_local_ai_hm_fixture_matrix.py"
RUNBOOK = ROOT / "docs/operations/LOCAL_AI_HM_THREE_SCENARIO_MATRIX.md"


class ThreeSyntheticHMScenarioPolicy(unittest.TestCase):
    def test_module_stays_pure_and_code_owned(self):
        source = MATRIX.read_text(encoding="utf-8")
        tree = ast.parse(source)
        module_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                module_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module_names.add(node.module or "")
        for forbidden in ("http", "requests", "openai", "sqlalchemy",
                          "socket", "subprocess", "os", "pathlib"):
            self.assertFalse(any(name == forbidden or name.startswith(forbidden + ".")
                                 for name in module_names))
        for marker in (
            '"complete_records"', '"missing_engine_records"',
            '"conflicting_alarm_times"', "evaluate_synthetic_source_quotes(",
            '"reference_expert_approved": False',
            '"model_digest_attested": False',
            '"real_model_executed": False',
            '"human_review_required": True',
            '"coverage_or_liability_decisions": False',
            '"pilot_accepted": False',
        ):
            self.assertIn(marker, source)

    def test_missing_and_conflicting_negative_cases_documented(self):
        tests = TESTS.read_text(encoding="utf-8")
        for marker in (
            "test_conflicting_accounts_remain_separate_and_unresolved",
            "test_invented_neglect_coverage_or_absence_cannot_be_attributed",
            "test_model_identity_and_prompt_cannot_claim_attestation",
            "test_input_unchanged_and_source_lineage_reclassification_rejected",
            "test_extra_claim_decision_is_not_accepted",
        ):
            self.assertIn(marker, tests)
        doc = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("Pilot GO=NO", doc)
        self.assertIn("not a certified expert", doc)


if __name__ == "__main__":
    unittest.main()

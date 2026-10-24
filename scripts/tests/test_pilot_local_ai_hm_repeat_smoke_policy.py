"""Always-on source-level guard for bounded, opt-in, synthetic AI repeat tests."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/pilot_local_ai_hm_repeat_smoke.py"
TESTS = ROOT / "apps/api/tests/test_local_ai_hm_repeat_smoke.py"
RUNBOOK = ROOT / "docs/operations/LOCAL_AI_HM_REPEAT_SMOKE.md"


class LocalAIRepeatSmokePolicy(unittest.TestCase):
    def test_no_arbitrary_input_or_unbounded_rounds_or_external_io(self):
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module)
        self.assertEqual(modules, {
            "__future__", "json", "sys", "typing", "app.ai.gateway.base",
            "app.ai.gateway.ollama_local",
            "scripts.pilot_local_ai_hm_fixture_matrix",
            "scripts.pilot_local_ai_hm_loopback_smoke",
        })
        for required in (
            "_ROUNDS = 3",
            'arguments != ["--run-fixed-synthetic-ollama-repeat-3"]',
            "run_fixed_three_scenario_smoke(provider)",
            "OllamaLocalExperimentalProvider(model=MODEL, max_output_tokens=512)",
            '"local_model_tag_unverified": MODEL',
            '"model_digest_attested": False',
            '"model_execution_independently_attested": False',
            '"repeatability_proven": False',
            '"context_preservation_expert_verified": False',
            '"context_pairs_missing_total"',
            '"context_not_evaluated_rounds"',
            '"expert_ground_truth_approved": False',
            '"human_review_completed": False',
            '"pilot_accepted": False',
            "except Exception:",
            'print("local_ai_synthetic_repeat_smoke_failed")',
        ):
            self.assertIn(required, source)
        for forbidden in (
            "open(", "read_text(", "write_text(", "write_bytes(",
            "requests.", "HTTPConnection(", "openai", "subprocess",
            "get_ai_provider(", "filename", "pathlib", "DATABASE_URL",
        ):
            self.assertNotIn(forbidden, source)

    def test_negative_tests_and_operator_warning(self):
        checks = TESTS.read_text(encoding="utf-8")
        for required in (
            "test_exact_nine_calls_and_bounded_success_metrics_without_prose",
            "test_partial_and_hallucinated_rounds_never_report_full_acceptance",
            "test_quote_gate_success_can_coexist_with_context_diagnostic_warning",
            "test_malformed_context_counters_fail_closed",
            "test_disconnected_localhost_is_safe_and_not_counted_as_success",
            "test_explicit_opt_in_required_before_constructing_provider",
            "test_unexpected_provider_error_never_leaks_data",
        ):
            self.assertIn(required, checks)
        guide = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("127.0.0.1:11434", guide)
        self.assertIn("--run-fixed-synthetic-ollama-repeat-3", guide)
        self.assertIn("Pilot GO=NO", guide)
        self.assertIn("does not independently verify", guide)


if __name__ == "__main__":
    unittest.main()

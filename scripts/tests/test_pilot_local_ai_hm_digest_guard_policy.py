"""Always-on static contract for local three-round digest drift guard."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/pilot_local_ai_hm_digest_guard_smoke.py"
TESTS = ROOT / "apps/api/tests/test_local_ai_hm_digest_guard_smoke.py"
RUNBOOK = ROOT / "docs/operations/LOCAL_AI_HM_DIGEST_GUARD_SMOKE.md"


class LocalAIDigestGuardPolicy(unittest.TestCase):
    def test_exact_flag_fixed_local_registry_and_nine_synthetic_calls(self):
        source = SCRIPT.read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {
            "__future__", "json", "re", "sys", "typing",
            "app.ai.gateway.base",
            "app.ai.gateway.ollama_local",
            "scripts.pilot_local_ai_model_inventory",
            "scripts.pilot_local_ai_hm_repeat_smoke",
        })
        for required in (
            'args != ["--run-fixed-synthetic-ollama-digest-guard"]',
            "inspect_fixed_local_model_inventory",
            "before = _observed_unattested_digest(observe_inventory())",
            "repeat = run_three_fixed_rounds(provider)",
            "after = _observed_unattested_digest(observe_inventory())",
            'unchanged = before == after',
            '"guarded_observation_accepted_for_human_review": unchanged and all_quotes',
            '"model_digest_attested": False',
            '"model_artifact_independently_attested": False',
            '"network_egress_isolation_verified": False',
            '"expert_ground_truth_approved": False',
            '"context_preservation_expert_verified": False',
            '"context_pairs_missing_total"',
            '"pilot_accepted": False',
            'print("local_model_digest_guard_failed")',
        ):
            self.assertIn(required, source)
        for prohibited in (
            'open(', 'write_text(', 'read_text(', 'write_bytes(',
            'requests.', 'http.client', 'HTTPConnection(', 'api/generate',
            'OpenAI(', 'subprocess', 'DATABASE_URL', 'get_ai_provider(',
        ):
            self.assertNotIn(prohibited, source)

    def test_negative_tests_and_operator_limits(self):
        tests = TESTS.read_text(encoding="utf-8")
        for required in (
            "test_exact_preflight_nine_requests_postflight_order",
            "test_digest_changed_after_nine_requests_denies_guarded_success",
            "test_missing_or_untrusted_preflight_never_calls_model",
            "test_postflight_missing_or_untrusted_fails_closed_without_success",
            "test_source_quote_incomplete_cannot_be_reported_as_guarded_success",
            "test_digest_guard_sanitizes_non_gate_context_warning",
            "test_digest_guard_refuses_invalid_context_summary",
            "test_digest_guard_rejects_impossible_aggregated_context_pairs",
            "test_digest_guard_refuses_unearned_approvals_in_repeat_summary",
            "test_cli_requires_one_exact_manual_flag_and_never_connects_without_it",
            "test_cli_sanitizes_unexpected_inventory_exceptions",
        ):
            self.assertIn(required, tests)
        guide = RUNBOOK.read_text(encoding="utf-8")
        for required in (
            "--run-fixed-synthetic-ollama-digest-guard",
            "127.0.0.1:11434", "nine", "Pilot GO=NO",
            "not independent attestation", "PowerShell",
        ):
            self.assertIn(required, guide)


if __name__ == "__main__":
    unittest.main()

"""Release policy guard for the explicit three-scenario local-only AI smoke."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/pilot_local_ai_hm_loopback_smoke.py"
TESTS = ROOT / "apps/api/tests/test_local_ai_hm_loopback_smoke.py"
RUNBOOK = ROOT / "docs/operations/LOCAL_AI_HM_LOOPBACK_SMOKE.md"


class LocalAISyntheticLoopbackSmokePolicy(unittest.TestCase):
    def test_script_requires_explicit_synthetic_opt_in_without_external_io(self):
        s = SCRIPT.read_text(encoding="utf-8")
        imports = set()
        for n in ast.walk(ast.parse(s)):
            if isinstance(n, ast.Import):
                imports.update(alias.name for alias in n.names)
            elif isinstance(n, ast.ImportFrom):
                imports.add(n.module or "")
        for prohibited in ("openai", "requests", "urllib", "socket",
                           "sqlalchemy", "subprocess", "pathlib", "os"):
            self.assertFalse(any(name == prohibited or name.startswith(prohibited + ".")
                                 for name in imports))
        for required in (
            '"--run-fixed-synthetic-ollama"',
            'if arguments != ["--run-fixed-synthetic-ollama"]:',
            'OllamaLocalExperimentalProvider(model=MODEL, max_output_tokens=512)',
            "metadata={\"synthetic_local_ai_test\": True}",
            "synthetic_source_catalog(scenario)",
            "evaluate_synthetic_scenario(scenario, candidate)",
            '"model_digest_attested": False',
            '"expert_ground_truth_approved": False',
            '"pilot_accepted": False',
            '"local_transport_attested": False',
            "except (AIProviderUnavailable, LocalAISourceGateError) as error:",
            "rejection_category",
            "_safe_rejection_category(error)",
            "observe_required_literal_quote_coverage(scenario, candidate)",
            '"source_quotes_incomplete_for_review"',
            '"critical_literal_coverage_observed"',
            '"unclassified_rejection"',
        ):
            self.assertIn(required, s)
        for forbidden in ("get_ai_provider(", "open(", "write_text(", "write_bytes(",
                          "http.client", "HTTPConnection(", "OpenAI("):
            self.assertNotIn(forbidden, s)

    def test_negative_tests_and_manual_runbook_present(self):
        t = TESTS.read_text(encoding="utf-8")
        for required in (
            "test_one_hallucination_rejected_without_stopping_other_cases",
            "test_unavailable_local_adapter_reports_safe_rejection_only",
            "test_wrong_provider_refused_without_model_call",
            "test_cli_requires_explicit_opt_in_and_does_not_contact_provider",
            "test_cli_unexpected_errors_hidden_without_stack_or_source_text",
        ):
            self.assertIn(required, t)
        d = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("127.0.0.1:11434", d)
        self.assertIn("ollama list", d)
        self.assertIn("Pilot GO=NO", d)
        self.assertIn("do not execute a real Ollama model", d)


if __name__ == "__main__":
    unittest.main()

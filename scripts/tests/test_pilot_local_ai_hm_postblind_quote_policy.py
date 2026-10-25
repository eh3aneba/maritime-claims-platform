"""Static release guard for manual synthetic-only post-blind quote revealing."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/pilot_local_ai_hm_postblind_model_quotes.py"
GUIDE = ROOT / "docs/operations/LOCAL_AI_HM_POSTBLIND_MODEL_QUOTES.md"


class PostblindSyntheticQuotePolicy(unittest.TestCase):
    def test_manual_opt_in_only_fixed_model_and_reconstructed_source(self):
        data = SOURCE.read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(data)):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {
            "__future__", "json", "sys", "typing",
            "app.ai.gateway.base", "app.ai.gateway.ollama_local",
            "scripts.pilot_local_ai_hm_fixture_matrix",
            "scripts.pilot_local_ai_hm_critical_quote_coverage",
            "scripts.pilot_local_ai_hm_loopback_smoke",
            "scripts.pilot_local_ai_hm_neutral_blind_packet",
            "scripts.pilot_local_ai_source_gate",
        })
        for required in (
            'args != ["--reveal-fixed-synthetic-ollama-quotes-for-postblind-review"]',
            "synthetic_source_catalog(scenario)",
            "observe_required_literal_quote_coverage(scenario, candidate)",
            'source["body"][start:end]',
            '"model_digest_attested": False',
            '"expert_labels_collected": False',
            '"independent_reference_frozen_verified": False',
            '"pilot_accepted": False',
            '"rejection_category": _safe_rejection_category(error)',
            'OllamaLocalExperimentalProvider(model=MODEL, max_output_tokens=512)',
        ):
            self.assertIn(required, data)
        for disallowed in (
            "open(", "read_text(", "write_text(", "write_bytes(",
            "subprocess", "get_ai_provider(", "DATABASE_URL",
            "requests.", "OpenAI(", "socket", "HTTPConnection(",
            "customer_document_loader",
        ):
            self.assertNotIn(disallowed, data)

    def test_operator_runbook_requires_separation_and_no_approval(self):
        guide = GUIDE.read_text(encoding="utf-8")
        for expected in (
            "Pilot GO=NO", "CASE-01", "human", "blind",
            "--reveal-fixed-synthetic-ollama-quotes-for-postblind-review",
            "127.0.0.1:11434",
        ):
            self.assertIn(expected, guide)


if __name__ == "__main__":
    unittest.main()

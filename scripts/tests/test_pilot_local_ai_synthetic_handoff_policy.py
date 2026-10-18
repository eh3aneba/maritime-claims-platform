"""Always-on non-network production policy: synthetic H&M AI handoff boundary."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "scripts" / "pilot_local_ai_synthetic_handoff.py"
TESTS = ROOT / "apps" / "api" / "tests" / "test_local_ai_synthetic_handoff.py"
GATE = ROOT / "scripts" / "pilot_local_ai_source_gate.py"
RUNBOOK = ROOT / "docs" / "operations" / "LOCAL_AI_SYNTHETIC_SOURCE_GATE.md"


class PilotLocalAIHandoffPolicy(unittest.TestCase):
    def test_no_untrusted_input_loader_or_case_database_mutation(self):
        s = HANDOFF.read_text(encoding="utf-8")
        for fragment in (
            "FIXTURE_SOURCES = {",
            "Synthetic Owner notification:",
            "Synthetic Chief Engineer statement:",
            "Synthetic intake:",
            '"synthetic_local_ai_test": True',
            'schema_name=SCHEMA',
            'output_schema=deepcopy(OUTPUT_SCHEMA)',
            'if getattr(provider, "name", None) != "ollama_local":',
            'evaluate_synthetic_source_quotes(FIXTURE_SOURCES, candidate)',
            '"model_digest_attested": False',
            '"model_semantics_verified": False',
            '"claim_mutations": False',
            '"pilot_accepted": False',
        ):
            self.assertIn(fragment, s)
        for forbidden in (
            "from app.modules.documents", "from app.db", "sqlalchemy",
            "requests.post", "OpenAI(", "Path(", "open(", "os.environ",
            "get_ai_provider(", "create_session(", "print(",
        ):
            self.assertNotIn(forbidden, s)
        self.assertIn('"human_review_required": True', GATE.read_text(encoding="utf-8"))

    def test_end_to_end_transport_is_mocked_and_safety_failures_covered(self):
        s = TESTS.read_text(encoding="utf-8")
        for marker in (
            "test_actual_ollama_adapter_mocked_socket_to_source_quote_verification",
            'patch("app.ai.gateway.ollama_local.http.client.HTTPConnection", FakeConn)',
            "test_unsupported_hallucinations_fail_closed_and_do_not_leak",
            "test_wrong_source_kind_version_free_text_or_empty_handoff_rejected",
            "test_response_model_and_provider_must_match",
            '"local_ai_source_quote_rejected"',
            '"model_digest_attested"',
        ):
            self.assertIn(marker, s)

    def test_no_pilot_authority_documented(self):
        s = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("mocked transport", s)
        self.assertIn("does not execute a real local model", s)
        self.assertIn("not a human approval", s)
        self.assertIn("Pilot GO remains NO", s)


if __name__ == "__main__":
    unittest.main()

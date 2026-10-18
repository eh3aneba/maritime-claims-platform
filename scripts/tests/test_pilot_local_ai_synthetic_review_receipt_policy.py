"""CI policy guard: synthetic AI receipt has no source disclosure or approval."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "scripts/pilot_local_ai_synthetic_review_receipt.py"
HANDOFF = ROOT / "scripts/pilot_local_ai_synthetic_handoff.py"
TESTS = ROOT / "apps/api/tests/test_local_ai_synthetic_review_receipt.py"
DOCS = ROOT / "docs/operations/LOCAL_AI_SYNTHETIC_SOURCE_GATE.md"


class LocalAIReviewReceiptPolicy(unittest.TestCase):
    def test_hash_only_receipt_no_real_file_or_persistence_paths(self):
        s = RECEIPT.read_text(encoding="utf-8")
        for marker in (
            "def build_pending_synthetic_review_receipt(",
            "evaluate_synthetic_hm_handoff(capture)",
            '"source_catalog_sha256": _fingerprint(FIXTURE_SOURCES)',
            '"request_sha256": capture.request_sha256',
            '"candidate_sha256": capture.response_sha256',
            '"status": "pending_unassigned_human_review"',
            '"model_digest_attested": False',
            '"reviewer_id": None',
            '"review_decision": None',
            '"authoritative_claim_changes": False',
            '"stored_in_database": False',
            '"pilot_accepted": False',
            '"receipt_sha256"',
        ):
            self.assertIn(marker, s)
        for forbidden in (
            "sqlalchemy", "create_session(", "open(", "Path(",
            "requests.", "OpenAI(", "http.client.HTTPConnection(",
            "get_ai_provider(", "print(", "logging.",
            "from app.modules.documents", "from app.modules.claims",
        ):
            self.assertNotIn(forbidden, s)

    def test_model_egress_and_review_remain_mocked(self):
        t = TESTS.read_text(encoding="utf-8")
        for token in (
            "test_mock_transport_runs_real_ollama_adapter_but_no_daemon",
            "test_unsupported_model_claims_never_produce_a_receipt",
            "test_wrong_provider_refused_before_any_model_call",
            "test_oversized_model_candidate_hash_denied_privately",
            "test_pending_receipt_is_stable_hash_only_and_not_a_review_or_authorization",
            "stored_in_database",
            "pending_unassigned_human_review",
        ):
            self.assertIn(token, t)
        h = HANDOFF.read_text(encoding="utf-8")
        self.assertIn("FIXTURE_SOURCES = {", h)
        self.assertIn('"synthetic_local_ai_test": True', h)

    def test_runbook_does_not_claim_live_review_or_approved_pilot(self):
        s = DOCS.read_text(encoding="utf-8")
        self.assertIn("hash-only pending review receipt", s)
        self.assertIn("not persisted", s)
        self.assertIn("no actual human reviewer", s)
        self.assertIn("Pilot GO remains NO", s)


if __name__ == "__main__":
    unittest.main()

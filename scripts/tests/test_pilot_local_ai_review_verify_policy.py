"""Production policy: local AI receipt validation cannot authorize review."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "scripts/pilot_local_ai_synthetic_review_verify.py"
TESTS = ROOT / "apps/api/tests/test_local_ai_synthetic_review_verify.py"
RUNBOOK = ROOT / "docs/operations/LOCAL_AI_SYNTHETIC_SOURCE_GATE.md"


class SyntheticReviewVerifyPolicy(unittest.TestCase):
    def test_exact_synthetic_receipt_and_pending_only_enforced(self):
        s = VERIFY.read_text(encoding="utf-8")
        for fragment in (
            "def verify_pending_synthetic_review_receipt(",
            "type(receipt) is not dict",
            "set(receipt) != _ALLOWED_KEYS",
            '"status": "pending_unassigned_human_review"',
            '"source_catalog_sha256"',
            '"request_sha256"',
            '"candidate_sha256"',
            'receipt["source_catalog_sha256"], _fingerprint(FIXTURE_SOURCES)',
            'receipt["request_sha256"], _expected_request_sha256()',
            'receipt["receipt_sha256"], _fingerprint(envelope, bounded=True)',
            '"reviewer_id": None',
            '"review_decision": None',
            '"model_digest_attested": False',
            '"may_auto_approve": False',
            '"persisted_to_review_queue": False',
            '"pilot_accepted": False',
        ):
            self.assertIn(fragment, s)
        for prohibited in (
            "sqlalchemy", "create_session(", "get_ai_provider(",
            "requests.", "OpenAI(", "http.client.", "Path(",
            "file.write(", "os.environ", "from app.modules.documents",
            "from app.modules.claims", "logging.",
        ):
            self.assertNotIn(prohibited, s)

    def test_negative_human_or_runtime_approval_cases_covered(self):
        s = TESTS.read_text(encoding="utf-8")
        for fragment in (
            "test_valid_synthetic_handoff_only_yields_non_authorizing_review_preview",
            "test_no_approval_or_scope_spoof_even_if_attacker_rehashes",
            "test_detect_unrehashed_body_tamper_without_claiming_signature",
            "test_source_catalog_change_or_request_drift_fails_even_if_rehashed",
            "test_rehashed_candidate_string_is_not_signer_authentication",
            "test_invalid_quote_count_cannot_be_marked_reviewable",
            'preview["may_auto_approve"] is False',
            'preview["model_digest_attested"] is False',
        ):
            self.assertIn(fragment, s)

    def test_runbook_records_remaining_real_authorization_work(self):
        s = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("read-only synthetic receipt verification", s)
        self.assertIn("unkeyed hash is not an authenticity signature", s)
        self.assertIn("not an authenticated human-review transition", s)
        self.assertIn("Pilot GO remains NO", s)


if __name__ == "__main__":
    unittest.main()

"""No-network synthetic review preview: safe receipt validation only."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from app.ai.gateway.base import AIProviderUnavailable, AIResponse
from scripts.pilot_local_ai_synthetic_review_receipt import (
    _fingerprint, build_pending_synthetic_review_receipt,
)
from scripts.pilot_local_ai_synthetic_review_verify import (
    verify_pending_synthetic_review_receipt,
)


class FakeSyntheticProvider:
    name = "ollama_local"

    def generate(self, request):
        assert request.metadata == {"synthetic_local_ai_test": True}
        return AIResponse(
            provider="ollama_local",
            model="qwen3:1.7b",
            structured_output={
                "items": [{
                    "kind": "reported_statement",
                    "source_id": "S2",
                    "source_version": "v1",
                    "verbatim_excerpt": "Abnormal vibration and high exhaust temperature were reported before shutdown.",
                }],
            },
        )


def _receipt():
    return build_pending_synthetic_review_receipt(FakeSyntheticProvider())


def _reject(receipt, code):
    with pytest.raises(AIProviderUnavailable) as exc:
        verify_pending_synthetic_review_receipt(receipt)
    assert str(exc.value) == code
    assert "vibration" not in str(exc.value)
    assert "Engineer" not in str(exc.value)


def test_valid_synthetic_handoff_only_yields_non_authorizing_review_preview():
    receipt = _receipt()
    first = verify_pending_synthetic_review_receipt(receipt)
    assert verify_pending_synthetic_review_receipt(receipt) == first
    assert first == {
        "scope": "synthetic_development_only",
        "status": "pending_unassigned_human_review",
        "receipt_sha256": receipt["receipt_sha256"],
        "candidate_sha256": receipt["candidate_sha256"],
        "quote_count": 1,
        "reviewer_authorized": False,
        "human_decision_recorded": False,
        "model_digest_attested": False,
        "may_auto_approve": False,
        "persisted_to_review_queue": False,
        "pilot_accepted": False,
    }
    assert not any(
        phrase in json.dumps(first)
        for phrase in ("Chief Engineer", "abnormal vibration", "claim_id", "document_id")
    )


@pytest.mark.parametrize("tamper", [
    {"status": "approved"}, {"reviewer_id": "synthetic-admin"},
    {"review_decision": "approved"}, {"model_digest_attested": True},
    {"stored_in_database": True}, {"pilot_accepted": True},
    {"authoritative_claim_changes": True}, {"scope": "production"},
    {"verified_quote_count": 1.0},
])
def test_no_approval_or_scope_spoof_even_if_attacker_rehashes(tamper):
    receipt = _receipt()
    receipt.update(tamper)
    receipt["receipt_sha256"] = _fingerprint({
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    })
    _reject(receipt, (
        "local_ai_review_receipt_invalid"
        if "verified_quote_count" in tamper
        else "local_ai_review_not_pending"
    ))


def test_detect_unrehashed_body_tamper_without_claiming_signature():
    receipt = _receipt()
    receipt["candidate_sha256"] = "a" * 64
    _reject(receipt, "local_ai_review_receipt_hash_mismatch")


def test_injected_extra_output_and_missing_field_are_refused():
    receipt = _receipt()
    receipt["model_generated_negligence"] = "The owner is liable"
    _reject(receipt, "local_ai_review_receipt_invalid")
    receipt = _receipt()
    receipt.pop("receipt_sha256")
    _reject(receipt, "local_ai_review_receipt_invalid")
    _reject([], "local_ai_review_receipt_invalid")


def test_source_catalog_change_or_request_drift_fails_even_if_rehashed():
    for key in ("source_catalog_sha256", "request_sha256"):
        receipt = _receipt()
        receipt[key] = "b" * 64
        receipt["receipt_sha256"] = _fingerprint({
            x: y for x, y in receipt.items() if x != "receipt_sha256"
        })
        _reject(receipt, "local_ai_review_fixture_changed")


@pytest.mark.parametrize("value", [None, False, 0, -1, 17, "1", 1.0])
def test_invalid_quote_count_cannot_be_marked_reviewable(value):
    receipt = _receipt()
    receipt["verified_quote_count"] = value
    _reject(receipt, "local_ai_review_receipt_invalid")


def test_invalid_digest_format_or_mismatched_prompt_version_rejected():
    receipt = _receipt()
    receipt["candidate_sha256"] = "not a hash"
    _reject(receipt, "local_ai_review_receipt_invalid")
    receipt = _receipt()
    receipt["prompt_version"] = "unexpected-new-v2"
    receipt["receipt_sha256"] = _fingerprint({
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    })
    _reject(receipt, "local_ai_review_not_pending")


def test_verified_preview_does_not_retain_model_prose_or_modify_receipt():
    receipt = _receipt()
    original = deepcopy(receipt)
    _ = verify_pending_synthetic_review_receipt(receipt)
    assert receipt == original
    assert receipt["reviewer_id"] is None
    assert receipt["review_decision"] is None


def test_rehashed_candidate_string_is_not_signer_authentication():
    # This is an intentional *limitation*: an attacker with write access
    # can forge a candidate hash and recompute the unkeyed receipt digest.
    # The preview therefore NEVER upgrades reviewer/model/pilot authority.
    receipt = _receipt()
    receipt["candidate_sha256"] = "b" * 64
    receipt["receipt_sha256"] = _fingerprint({
        x: y for x, y in receipt.items() if x != "receipt_sha256"
    })
    preview = verify_pending_synthetic_review_receipt(receipt)
    assert preview["may_auto_approve"] is False
    assert preview["model_digest_attested"] is False
    assert preview["persisted_to_review_queue"] is False

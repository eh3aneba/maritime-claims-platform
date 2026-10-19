"""Fail-closed, read-only review handoff validation for synthetic AI receipts.

This is NOT reviewer authentication, a signature, a database queue or
production approval. It only verifies exact development-fixture binding,
canonical unmodified receipt digest and explicit pending/unassigned flags.
"""
from __future__ import annotations

import hmac
import re
from typing import Any

from app.ai.gateway.base import AIProviderUnavailable
from scripts.pilot_local_ai_synthetic_handoff import (
    FIXTURE_SOURCES, MODEL, PROMPT_VERSION, SCHEMA,
    build_synthetic_hm_request,
)
from scripts.pilot_local_ai_synthetic_review_receipt import (
    RECEIPT_SCHEMA, _fingerprint,
)

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_KEYS = frozenset({
    "schema", "scope", "status", "source_catalog_sha256",
    "request_sha256", "candidate_sha256", "prompt_version",
    "source_schema", "model_tag_unverified", "model_digest_attested",
    "verified_quote_count", "reviewer_id", "review_decision",
    "authoritative_claim_changes", "stored_in_database",
    "pilot_accepted", "receipt_sha256",
})
_REQUIRED = {
    "schema": RECEIPT_SCHEMA,
    "scope": "synthetic_development_only",
    "status": "pending_unassigned_human_review",
    "prompt_version": PROMPT_VERSION,
    "source_schema": SCHEMA,
    "model_tag_unverified": MODEL,
    "model_digest_attested": False,
    "reviewer_id": None,
    "review_decision": None,
    "authoritative_claim_changes": False,
    "stored_in_database": False,
    "pilot_accepted": False,
}


def _expected_request_sha256() -> str:
    request = build_synthetic_hm_request()
    return _fingerprint({
        "task": request.task,
        "system_instructions": request.system_instructions,
        "input_text": request.input_text,
        "schema_name": request.schema_name,
        "output_schema": request.output_schema,
        "metadata": request.metadata,
    }, bounded=True)


def verify_pending_synthetic_review_receipt(receipt: object) -> dict[str, Any]:
    """Check only fixture-integrity/provenance shape; never accept a human decision.

    An attacker with rewrite access can forge both a candidate digest and
    receipt digest. No trusted signer, model checksum or verified human exists.
    Do NOT elevate this result to a real review queue or Pilot GO.
    """
    if type(receipt) is not dict or set(receipt) != _ALLOWED_KEYS:
        raise AIProviderUnavailable("local_ai_review_receipt_invalid")
    if any(type(receipt[key]) is not type(value) or receipt[key] != value
           for key, value in _REQUIRED.items()):
        raise AIProviderUnavailable("local_ai_review_not_pending")
    if (
        type(receipt["verified_quote_count"]) is not int
        or not 1 <= receipt["verified_quote_count"] <= 16
        or any(type(receipt[key]) is not str or not _HEX.fullmatch(receipt[key])
               for key in (
                   "source_catalog_sha256", "request_sha256",
                   "candidate_sha256", "receipt_sha256",
               ))
    ):
        raise AIProviderUnavailable("local_ai_review_receipt_invalid")

    if (
        not hmac.compare_digest(
            receipt["source_catalog_sha256"], _fingerprint(FIXTURE_SOURCES)
        )
        or not hmac.compare_digest(
            receipt["request_sha256"], _expected_request_sha256()
        )
    ):
        raise AIProviderUnavailable("local_ai_review_fixture_changed")

    # This detects accidental/unauthorized field changes *without* a
    # recomputed hash. It is NOT a cryptographic integrity signature.
    envelope = {key: value for key, value in receipt.items()
                if key != "receipt_sha256"}
    if not hmac.compare_digest(
        receipt["receipt_sha256"], _fingerprint(envelope, bounded=True)
    ):
        raise AIProviderUnavailable("local_ai_review_receipt_hash_mismatch")

    # Sanitized preview only: no prompts, quotes, authorizing reviewers,
    # timestamps, organization IDs, claim IDs, side-effects or decisions.
    return {
        "scope": "synthetic_development_only",
        "status": "pending_unassigned_human_review",
        "receipt_sha256": receipt["receipt_sha256"],
        "candidate_sha256": receipt["candidate_sha256"],
        "quote_count": receipt["verified_quote_count"],
        "reviewer_authorized": False,
        "human_decision_recorded": False,
        "model_digest_attested": False,
        "may_auto_approve": False,
        "persisted_to_review_queue": False,
        "pilot_accepted": False,
    }

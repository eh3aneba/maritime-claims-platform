"""Deterministic, non-persistent synthetic H&M quote-review receipt.

Runs ONLY the existing code-owned invented source fixture through the
development-only Ollama provider handoff. No user text, file path, database,
claim ID, credentials or PII enters this function. Receipt is hash-only and
does not contain model prose or a human review decision.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.ai.gateway.base import AIProvider, AIProviderUnavailable, AIRequest, AIResponse
from scripts.pilot_local_ai_synthetic_handoff import (
    FIXTURE_SOURCES, MODEL, PROMPT_VERSION, SCHEMA,
    evaluate_synthetic_hm_handoff,
)

RECEIPT_SCHEMA = "seeclaims-synthetic-local-ai-pending-review-receipt-v1"
MAX_STRUCTURED_RESPONSE_BYTES = 65_536


def _fingerprint(obj: Any, *, bounded: bool = False) -> str:
    """Canonical JSON fingerprint; never include private raw content in errors."""
    try:
        raw = json.dumps(
            obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise AIProviderUnavailable("local_ai_review_fingerprint_invalid") from None
    if bounded and len(raw) > MAX_STRUCTURED_RESPONSE_BYTES:
        raise AIProviderUnavailable("local_ai_review_response_too_large")
    return hashlib.sha256(raw).hexdigest()


class _HashOnlyCapture:
    """Capture fingerprints; do not retain or return source/model raw text."""

    name = "ollama_local"

    def __init__(self, inner: AIProvider) -> None:
        self.inner = inner
        self.request_sha256: str | None = None
        self.response_sha256: str | None = None

    def generate(self, request: AIRequest) -> AIResponse:
        self.request_sha256 = _fingerprint({
            "task": request.task,
            "system_instructions": request.system_instructions,
            "input_text": request.input_text,
            "schema_name": request.schema_name,
            "output_schema": request.output_schema,
            "metadata": request.metadata,
        }, bounded=True)
        response = self.inner.generate(request)
        if type(response.structured_output) is dict:
            self.response_sha256 = _fingerprint(
                response.structured_output, bounded=True,
            )
        return response


def build_pending_synthetic_review_receipt(provider: AIProvider) -> dict[str, Any]:
    """Return only an unassigned review receipt; no persistence or approval.

    Validation of *meaning*, actual model artifact digest, reviewer identity,
    legitimate Evidence rights and customer-data provenance is out of scope.
    """
    if getattr(provider, "name", None) != "ollama_local":
        raise AIProviderUnavailable("local_ai_provider_not_allowed")
    capture = _HashOnlyCapture(provider)
    handoff = evaluate_synthetic_hm_handoff(capture)
    if (
        capture.request_sha256 is None or capture.response_sha256 is None
        or handoff["status"] != "synthetic_quotes_pending_human_review"
        or handoff["pilot_accepted"] is not False
        or handoff["model_digest_attested"] is not False
        or handoff["claim_mutations"] is not False
    ):
        raise AIProviderUnavailable("local_ai_review_receipt_denied")
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "scope": "synthetic_development_only",
        "status": "pending_unassigned_human_review",
        "source_catalog_sha256": _fingerprint(FIXTURE_SOURCES),
        "request_sha256": capture.request_sha256,
        "candidate_sha256": capture.response_sha256,
        "prompt_version": PROMPT_VERSION,
        "source_schema": SCHEMA,
        "model_tag_unverified": MODEL,
        "model_digest_attested": False,
        "verified_quote_count": handoff["verified_quote_count"],
        "reviewer_id": None,
        "review_decision": None,
        "authoritative_claim_changes": False,
        "stored_in_database": False,
        "pilot_accepted": False,
    }
    # Useful for synthetic test deduplication, NOT a digital signature.
    receipt["receipt_sha256"] = _fingerprint(receipt)
    return receipt

"""Synthetic local-AI review receipt tests: no DB, no real model or network."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from app.ai.gateway.base import AIProviderUnavailable, AIResponse
from app.ai.gateway.ollama_local import OllamaLocalExperimentalProvider
from scripts.pilot_local_ai_synthetic_review_receipt import (
    RECEIPT_SCHEMA, build_pending_synthetic_review_receipt,
)


def _item(text="Abnormal vibration and high exhaust temperature were reported before shutdown."):
    return {
        "kind": "reported_statement",
        "source_id": "S2",
        "source_version": "v1",
        "verbatim_excerpt": text,
    }


class FakeLocalAI:
    name = "ollama_local"

    def __init__(self, *, items=None, output=None):
        self.output = {"items": [_item()]} if output is None else output
        if items is not None:
            self.output = {"items": items}
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        assert request.metadata == {"synthetic_local_ai_test": True}
        return AIResponse(
            provider="ollama_local",
            model="qwen3:1.7b",
            structured_output=self.output,
        )


def test_pending_receipt_is_stable_hash_only_and_not_a_review_or_authorization():
    provider = FakeLocalAI()
    first = build_pending_synthetic_review_receipt(provider)
    second = build_pending_synthetic_review_receipt(provider)
    assert first == second
    assert provider.calls == 2
    assert first["schema"] == RECEIPT_SCHEMA
    assert first["status"] == "pending_unassigned_human_review"
    assert first["scope"] == "synthetic_development_only"
    assert first["reviewer_id"] is None and first["review_decision"] is None
    assert first["model_digest_attested"] is False
    assert first["stored_in_database"] is False
    assert first["authoritative_claim_changes"] is False
    assert first["pilot_accepted"] is False
    assert first["verified_quote_count"] == 1
    for key in ("source_catalog_sha256", "request_sha256", "candidate_sha256", "receipt_sha256"):
        assert len(first[key]) == 64
        assert all(c in "0123456789abcdef" for c in first[key])
    for sensitive in ("turbocharger", "Chief Engineer", "vibration", "Engine logs", "liability", "negligence", "document_id", "claim_id"):
        assert sensitive.lower() not in json.dumps(first).lower()


def test_different_source_supported_quote_changes_candidate_and_receipt_hash():
    standard = build_pending_synthetic_review_receipt(FakeLocalAI())
    supported = build_pending_synthetic_review_receipt(FakeLocalAI(
        items=[_item(text="Abnormal vibration")],
    ))
    assert standard["source_catalog_sha256"] == supported["source_catalog_sha256"]
    assert standard["request_sha256"] == supported["request_sha256"]
    assert standard["candidate_sha256"] != supported["candidate_sha256"]
    assert standard["receipt_sha256"] != supported["receipt_sha256"]
    assert supported["review_decision"] is None


@pytest.mark.parametrize("bad", [
    "Chief Engineer confirmed the bearing failed from negligence.",
    "Missing logs prove lack of maintenance.",
    "The H&M policy will pay this claim.",
    "Engine logs never existed.",
])
def test_unsupported_model_claims_never_produce_a_receipt(bad):
    with pytest.raises(AIProviderUnavailable, match="local_ai_source_quote_rejected") as error:
        build_pending_synthetic_review_receipt(FakeLocalAI(items=[_item(text=bad)]))
    assert bad not in str(error.value)


@pytest.mark.parametrize("output", [
    {"items": []},
    {"items": [_item()], "approval": True},
    {"items": [_item()] * 33},
])
def test_invalid_candidate_has_no_receipt(output):
    with pytest.raises(AIProviderUnavailable):
        build_pending_synthetic_review_receipt(FakeLocalAI(output=output))


def test_wrong_provider_refused_before_any_model_call():
    provider = FakeLocalAI()
    provider.name = "openai"
    with pytest.raises(AIProviderUnavailable, match="local_ai_provider_not_allowed"):
        build_pending_synthetic_review_receipt(provider)
    assert provider.calls == 0


def test_oversized_model_candidate_hash_denied_privately():
    # The transport has its own cap; this defense-in-depth covers injected fake providers.
    oversized = FakeLocalAI(items=[_item(text="x" * 70_000)])
    with pytest.raises(AIProviderUnavailable) as error:
        build_pending_synthetic_review_receipt(oversized)
    assert str(error.value) == "local_ai_review_response_too_large"
    assert "x" * 50 not in str(error.value)


def test_mock_transport_runs_real_ollama_adapter_but_no_daemon():
    observed = {}

    class FakeConn:
        def __init__(self, host, port, timeout):
            observed["endpoint"] = (host, port, timeout)

        def request(self, method, path, *, body, headers):
            observed["path"] = path
            observed["method"] = method
            observed["payload"] = json.loads(body)

        def getresponse(self):
            class Reply:
                status = 200

                def read(self, _limit):
                    return json.dumps({
                        "model": "qwen3:1.7b",
                        "done": True,
                        "response": json.dumps({"items": [_item()]}),
                    }).encode("utf-8")
            return Reply()

        def close(self):
            observed["closed"] = True

    provider = OllamaLocalExperimentalProvider(model="qwen3:1.7b")
    with patch("app.ai.gateway.ollama_local.http.client.HTTPConnection", FakeConn):
        receipt = build_pending_synthetic_review_receipt(provider)
    assert observed["endpoint"] == ("127.0.0.1", 11434, 10)
    assert observed["method"] == "POST"
    assert observed["path"] == "/api/generate"
    assert observed["payload"]["think"] is False
    assert observed["payload"]["stream"] is False
    assert observed["closed"]
    assert receipt["status"] == "pending_unassigned_human_review"
    assert receipt["stored_in_database"] is False

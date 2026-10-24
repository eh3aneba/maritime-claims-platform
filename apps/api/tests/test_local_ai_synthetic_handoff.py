"""GitHub-only fake-network end-to-end smoke for H&M local source custody."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from app.ai.gateway.base import AIProviderUnavailable, AIResponse
from app.ai.gateway.ollama_local import OllamaLocalExperimentalProvider
from scripts.pilot_local_ai_synthetic_handoff import (
    FIXTURE_SOURCES, MODEL, SCHEMA,
    build_synthetic_hm_request, evaluate_synthetic_hm_handoff,
)


def _quote(source_id="S2", text=None, kind="reported_statement", version="v1"):
    return {
        "kind": kind, "source_id": source_id,
        "source_version": version,
        "verbatim_excerpt": (
            "Abnormal vibration and high exhaust temperature were reported before shutdown."
            if text is None else text
        ),
    }


class _StubProvider:
    name = "ollama_local"

    def __init__(self, output, *, model=MODEL, provider="ollama_local"):
        self.output = output
        self.model = model
        self.provider = provider
        self.last_request = None

    def generate(self, request):
        self.last_request = request
        return AIResponse(
            provider=self.provider, model=self.model, structured_output=self.output,
        )


def test_fixed_synthetic_request_never_sends_actual_claim_metadata():
    request = build_synthetic_hm_request()
    assert request.metadata == {"synthetic_local_ai_test": True}
    assert request.task == "synthetic_hm_source_quote_review"
    assert request.schema_name == SCHEMA
    assert request.output_schema["additionalProperties"] is False
    assert request.output_schema["properties"]["items"]["items"]["additionalProperties"] is False
    assert "S1 | event_notice | v1" in request.input_text
    assert "S2 | reported_statement | v1" in request.input_text
    assert "S3 | intake_status | v1" in request.input_text
    assert "Engine logs" in request.input_text
    assert "not supplied" in request.system_instructions
    assert not any(k in request.metadata for k in ("claim_id", "document_id", "organization_id"))
    assert all(data["body"].startswith("Synthetic") for data in FIXTURE_SOURCES.values())


def test_mocked_model_exact_quote_routes_only_to_human_review():
    provider = _StubProvider({"items": [_quote()]})
    result = evaluate_synthetic_hm_handoff(provider)
    assert provider.last_request.metadata == {"synthetic_local_ai_test": True}
    assert result == {
        "status": "synthetic_quotes_pending_human_review",
        "verified_quote_count": 1,
        "model_digest_attested": False,
        "model_semantics_verified": False,
        "actual_model_execution_required": True,
        "claim_mutations": False,
        "pilot_accepted": False,
    }
    assert "vibration" not in str(result)


@pytest.mark.parametrize("bad_quote", [
    "Chief Engineer confirmed the bearing failed from negligence.",
    "Engine logs do not exist; there was no maintenance.",
    "H&M coverage is confirmed and settlement approved.",
    "The Owner claimed the failure was unrelated to maintenance.",
])
def test_unsupported_hallucinations_fail_closed_and_do_not_leak(bad_quote):
    provider = _StubProvider({"items": [_quote(text=bad_quote)]})
    with pytest.raises(AIProviderUnavailable) as caught:
        evaluate_synthetic_hm_handoff(provider)
    assert str(caught.value) == "local_ai_source_quote_rejected"
    assert bad_quote not in str(caught.value)


@pytest.mark.parametrize("output", [
    {"items": [_quote(source_id="S9")]},
    {"items": [_quote(kind="event_notice")]},
    {"items": [_quote(version="v2")]},
    {"items": [_quote()], "liability": "approved"},
    {"items": []},
])
def test_wrong_source_kind_version_free_text_or_empty_handoff_rejected(output):
    provider = _StubProvider(output)
    with pytest.raises(AIProviderUnavailable, match="local_ai_"):
        evaluate_synthetic_hm_handoff(provider)


def test_response_model_and_provider_must_match():
    for candidate in (
        _StubProvider({"items": [_quote()]}, model="qwen3:4b"),
        _StubProvider({"items": [_quote()]}, provider="openai"),
    ):
        with pytest.raises(AIProviderUnavailable, match="local_ai_invalid_handoff"):
            evaluate_synthetic_hm_handoff(candidate)
    outsider = _StubProvider({"items": [_quote()]})
    outsider.name = "openai"
    with pytest.raises(AIProviderUnavailable, match="local_ai_provider_not_allowed"):
        evaluate_synthetic_hm_handoff(outsider)
    assert outsider.last_request is None


def test_actual_ollama_adapter_mocked_socket_to_source_quote_verification():
    observed = {}

    class FakeConn:
        def __init__(self, host, port, timeout):
            observed["destination"] = (host, port, timeout)

        def request(self, method, path, *, body, headers):
            observed["route"] = (method, path)
            observed["payload"] = json.loads(body)
            observed["headers"] = headers

        def getresponse(self):
            class FakeReply:
                status = 200
                def read(self, limit):
                    payload = {
                        "model": MODEL, "done": True,
                        "response": json.dumps({"items": [_quote()]}),
                    }
                    return json.dumps(payload).encode("utf-8")
            return FakeReply()

        def close(self):
            observed["closed"] = True

    provider = OllamaLocalExperimentalProvider(model=MODEL, max_output_tokens=256)
    with patch("app.ai.gateway.ollama_local.http.client.HTTPConnection", FakeConn):
        report = evaluate_synthetic_hm_handoff(provider)
    assert observed["destination"] == ("127.0.0.1", 11434, 30)
    assert observed["route"] == ("POST", "/api/generate")
    assert observed["payload"]["think"] is False
    assert observed["payload"]["stream"] is False
    assert observed["payload"]["format"]["additionalProperties"] is False
    assert observed["closed"] is True
    assert report["verified_quote_count"] == 1
    assert report["model_digest_attested"] is False
    assert report["pilot_accepted"] is False

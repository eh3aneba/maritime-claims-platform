import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from app.ai.gateway.base import AIResponse
from app.modules.claims.facts import ClaimFact
from app.modules.evidence_search import qa_synthesis_service as synthesis
from app.modules.evidence_search.qa_synthesis_models import ClaimQaSynthesisRun
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_document_processing import login, seed_claim
from tests.test_evidence_search import _add_processed_document


def setup_function() -> None:
    reset_database()


def _seed_answerable() -> dict:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="Engine_Log_QA.txt",
        document_type="engine_log",
        text="The engine log records 14,250 turbocharger running hours before casualty.",
        locator="9",
    )
    login("alpha", "alpha@example.com")
    return ids


def _post(claim_id: str, question: str, **overrides):
    return client.post(
        f"/api/v1/claims/{claim_id}/evidence-search/qa/synthesize",
        json={
            "question": question,
            "retrieval_mode": "hybrid",
            "top_k": 5,
            "fallback_to_extractive": True,
            **overrides,
        },
    )


def _fake_authorization():
    return SimpleNamespace(
        id=None,
        model="mock-governed-model",
        prompt_bundle_version="qa-prompt-v1",
        schema_bundle_version="qa-schema-v1",
        decision_hash="a" * 64,
        policy_hash="b" * 64,
        max_input_chars=20000,
        environment="production",
    )


class _GroundedProvider:
    name = "openai"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        payload = json.loads(request.input_text)
        unit = payload["evidence_bundle"][0]
        return AIResponse(
            provider="openai",
            model="mock-governed-model",
            structured_output={
                "statements": [
                    {
                        "text": "The engine log records 14,250 turbocharger running hours before casualty.",
                        "evidence": [
                            {
                                "source_unit_id": unit["source_unit_id"],
                                "quote": "14,250 turbocharger running hours before casualty",
                            }
                        ],
                    }
                ]
            },
            usage={"input_tokens": 100, "output_tokens": 25, "total_tokens": 125},
            raw_response_id="synthetic-provider-response-1",
        )


class _FabricatingProvider(_GroundedProvider):
    def generate(self, request):
        self.calls += 1
        return AIResponse(
            provider="openai",
            model="mock-governed-model",
            structured_output={
                "statements": [
                    {
                        "text": "The workshop is liable and must pay the claim.",
                        "evidence": [
                            {
                                "source_unit_id": "00000000-0000-0000-0000-000000000000",
                                "quote": "invented evidence",
                            }
                        ],
                    }
                ]
            },
            usage={"input_tokens": 90, "output_tokens": 20, "total_tokens": 110},
            raw_response_id="synthetic-provider-response-bad",
        )


def test_governed_synthesis_without_production_authorization_makes_zero_provider_calls(monkeypatch) -> None:
    ids = _seed_answerable()

    def forbidden_provider():
        raise AssertionError("Provider must not be resolved or called without active Production-wide authorization")

    monkeypatch.setattr(synthesis, "get_ai_provider", forbidden_provider)
    response = _post(ids["claim_id"], "What were the turbocharger running hours before casualty?")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["status"] == "answered"
    assert payload["synthesis_used"] is False
    assert payload["fallback_used"] is True
    assert payload["synthesis_failure_code"] == "no_production_wide_authorization"
    assert payload["claim_facts_updated"] is False
    assert "14,250" in payload["answer"]

    with TestingSessionLocal() as db:
        run = db.scalar(select(ClaimQaSynthesisRun).where(ClaimQaSynthesisRun.claim_id == UUID(ids["claim_id"])))
        assert run is not None
        assert run.status == "blocked"
        assert run.provider_call_made is False
        assert run.failure_code == "no_production_wide_authorization"
        assert len(run.question_hash) == 64
        assert len(run.result_set_hash) == 64


def test_governed_synthesis_can_fail_closed_without_extractive_fallback(monkeypatch) -> None:
    ids = _seed_answerable()
    monkeypatch.setattr(synthesis, "get_ai_provider", lambda: (_ for _ in ()).throw(AssertionError("no provider call")))

    response = _post(
        ids["claim_id"],
        "What were the turbocharger running hours before casualty?",
        fallback_to_extractive=False,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "synthesis_blocked"
    assert payload["statements"] == []
    assert payload["synthesis_used"] is False
    assert payload["fallback_used"] is False


def test_authorized_mocked_gateway_returns_only_verified_source_linked_statements(monkeypatch) -> None:
    ids = _seed_answerable()
    provider = _GroundedProvider()
    authorization = _fake_authorization()
    monkeypatch.setattr(synthesis, "_authorize_bundle", lambda *args, **kwargs: (authorization, []))
    monkeypatch.setattr(synthesis, "get_settings", lambda: SimpleNamespace(ai_provider="openai"))
    monkeypatch.setattr(synthesis, "get_ai_provider", lambda: provider)

    with TestingSessionLocal() as db:
        before = list(db.scalars(select(ClaimFact).where(ClaimFact.claim_id == UUID(ids["claim_id"]))))
    response = _post(ids["claim_id"], "What were the turbocharger running hours before casualty?")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert provider.calls == 1
    assert payload["status"] == "answered"
    assert payload["synthesis_used"] is True
    assert payload["fallback_used"] is False
    assert payload["provider"] == "openai"
    assert payload["model"] == "mock-governed-model"
    assert payload["answer_engine_version"] == "12G.1"
    assert payload["statements"][0]["source_refs"]
    assert "14,250" in payload["answer"]
    assert len(payload["input_hash"]) == 64
    assert len(payload["output_hash"]) == 64

    with TestingSessionLocal() as db:
        after = list(db.scalars(select(ClaimFact).where(ClaimFact.claim_id == UUID(ids["claim_id"]))))
        run = db.scalar(select(ClaimQaSynthesisRun).where(ClaimQaSynthesisRun.claim_id == UUID(ids["claim_id"])))
        assert len(after) == len(before)
        assert run is not None
        assert run.status == "completed"
        assert run.provider_call_made is True
        assert run.provider == "openai"
        assert run.input_tokens == 100
        assert run.output_tokens == 25
        assert run.total_tokens == 125


def test_fabricated_source_or_authority_crossing_is_rejected_and_falls_back(monkeypatch) -> None:
    ids = _seed_answerable()
    provider = _FabricatingProvider()
    authorization = _fake_authorization()
    monkeypatch.setattr(synthesis, "_authorize_bundle", lambda *args, **kwargs: (authorization, []))
    monkeypatch.setattr(synthesis, "get_settings", lambda: SimpleNamespace(ai_provider="openai"))
    monkeypatch.setattr(synthesis, "get_ai_provider", lambda: provider)

    response = _post(ids["claim_id"], "What were the turbocharger running hours before casualty?")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert provider.calls == 1
    assert payload["status"] == "answered"
    assert payload["synthesis_used"] is False
    assert payload["fallback_used"] is True
    assert payload["synthesis_failure_code"] == "grounding_verification_failed"
    assert "liable" not in payload["answer"].lower()
    assert "14,250" in payload["answer"]

    with TestingSessionLocal() as db:
        run = db.scalar(select(ClaimQaSynthesisRun).where(ClaimQaSynthesisRun.claim_id == UUID(ids["claim_id"])))
        assert run is not None
        assert run.status == "verification_failed"
        assert run.output_hash is not None
        assert run.provider_call_made is True


def test_raw_question_is_not_persisted_in_synthesis_ledger(monkeypatch) -> None:
    ids = _seed_answerable()
    question = "What were the turbocharger running hours before casualty? UNIQUE_RAW_QUESTION_MARKER"
    monkeypatch.setattr(synthesis, "get_ai_provider", lambda: (_ for _ in ()).throw(AssertionError("no provider call")))

    response = _post(ids["claim_id"], question)
    assert response.status_code == 200, response.text

    with TestingSessionLocal() as db:
        run = db.scalar(select(ClaimQaSynthesisRun).where(ClaimQaSynthesisRun.claim_id == UUID(ids["claim_id"])))
        assert run is not None
        persisted = {
            column.name: getattr(run, column.name)
            for column in run.__table__.columns
        }
        assert "UNIQUE_RAW_QUESTION_MARKER" not in json.dumps(persisted, default=str)
        assert len(run.question_hash) == 64

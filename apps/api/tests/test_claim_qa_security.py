from uuid import UUID, uuid4

from app.modules.documents.models import ConfidentialityLevel
from tests.db_harness import client, reset_database
from tests.test_document_processing import login, seed_claim
from tests.test_evidence_search import _add_processed_document


def setup_function() -> None:
    reset_database()


def _ask(claim_id: str, question: str, **overrides) -> dict:
    response = client.post(
        f"/api/v1/claims/{claim_id}/evidence-search/qa",
        json={"question": question, "retrieval_mode": "hybrid", "top_k": 10, **overrides},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_claim_qa_enforces_tenant_claim_scope() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="Alpha_Private_Evidence.txt",
        document_type="engine_log",
        text="Alpha-only turbocharger evidence records an emergency shutdown before casualty.",
        locator="4",
    )

    login("beta", "beta@example.com")
    response = client.post(
        f"/api/v1/claims/{ids['claim_id']}/evidence-search/qa",
        json={"question": "What evidence records an emergency shutdown?", "retrieval_mode": "hybrid"},
    )
    assert response.status_code == 404


def test_restricted_evidence_is_answered_only_through_local_private_semantic_path() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="Restricted_Engine_Log.txt",
        document_type="engine_log",
        text="Restricted evidence records 14,250 turbocharger running hours before casualty.",
        locator="9",
        confidentiality=ConfidentialityLevel.RESTRICTED,
    )
    login("alpha", "alpha@example.com")

    result = _ask(ids["claim_id"], "What were the turbocharger operating hours before casualty?")

    assert result["status"] == "answered"
    assert result["semantic_used"] is True
    assert result["semantic_provider"] == "local_in_process"
    assert result["semantic_model"] == "marine-concepts-hash-v1"
    assert result["statements"][0]["source_refs"][0]["confidentiality_level"] == "restricted"


def test_superseded_evidence_is_excluded_by_default_and_requires_explicit_opt_in() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    family_id = uuid4()
    old_id = _add_processed_document(
        claim_id=claim_id,
        filename="PMS_Interval_v1.txt",
        document_type="pms_history",
        text="Turbocharger overhaul interval was recorded as 12,000 running hours.",
        locator="1",
        family_id=family_id,
        version=1,
        is_current=False,
    )
    new_id = _add_processed_document(
        claim_id=claim_id,
        filename="PMS_Interval_v2.txt",
        document_type="pms_history",
        text="Turbocharger overhaul interval was revised to 10,000 running hours.",
        locator="2",
        family_id=family_id,
        version=2,
        is_current=True,
        supersedes_document_id=old_id,
    )
    login("alpha", "alpha@example.com")

    current = _ask(ids["claim_id"], "What is the turbocharger overhaul interval?")
    current_sources = [
        source["document_id"]
        for statement in current["statements"]
        for source in statement["source_refs"]
    ]
    assert str(new_id) in current_sources
    assert str(old_id) not in current_sources

    historical = _ask(
        ids["claim_id"],
        "What is the turbocharger overhaul interval?",
        include_superseded=True,
    )
    historical_sources = {
        source["document_id"]
        for statement in historical["statements"]
        for source in statement["source_refs"]
    }
    assert historical_sources == {str(old_id), str(new_id)}
    assert historical["status"] == "conflicting_evidence"
    assert any(conflict["conflict_type"] == "numeric_disagreement" for conflict in historical["conflicts"])

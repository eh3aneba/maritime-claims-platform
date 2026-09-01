from uuid import UUID

from sqlalchemy import func, select

from app.modules.claims.facts import ClaimFact
from app.modules.evidence_search.models import ClaimEvidenceSearchRun
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_document_processing import login, seed_claim
from tests.test_evidence_search import _add_processed_document


def setup_function() -> None:
    reset_database()


def _ask(claim_id: str, question: str, **overrides) -> dict:
    payload = {
        "question": question,
        "top_k": 5,
        "retrieval_mode": "hybrid",
        **overrides,
    }
    response = client.post(f"/api/v1/claims/{claim_id}/evidence-search/qa", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_grounded_qa_returns_only_source_linked_extractive_statements() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    document_id = _add_processed_document(
        claim_id=claim_id,
        filename="PMS_Overhaul_Record.txt",
        document_type="pms_history",
        text="Turbocharger overhaul completed on 20 June 2026 at 11,800 running hours. Bearings and rotor were inspected.",
        locator="12",
    )
    login("alpha", "alpha@example.com")

    result = _ask(ids["claim_id"], "When was the machinery last serviced?")

    assert result["status"] == "answered"
    assert result["answer_engine_version"] == "12F.1"
    assert result["retrieval_mode"] == "hybrid"
    assert result["semantic_provider"] == "local_in_process"
    assert result["claim_facts_updated"] is False
    assert result["non_authoritative"] is True
    assert len(result["question_hash"]) == 64
    assert len(result["result_set_hash"]) == 64
    assert len(result["answer_hash"]) == 64
    assert result["statements"]
    statement = result["statements"][0]
    assert statement["text"] in result["answer"]
    assert "20 June 2026" in statement["text"]
    assert len(statement["statement_hash"]) == 64
    assert len(statement["source_refs"]) == 1
    source = statement["source_refs"][0]
    assert source["document_id"] == str(document_id)
    assert source["document_version"] == 1
    assert source["locator_type"] == "page"
    assert source["locator_value"] == "12"
    assert len(source["search_unit_hash"]) == 64


def test_grounded_qa_fails_closed_when_no_evidence_exists() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="Workshop_Report.txt",
        document_type="workshop_report",
        text="Workshop inspected the removed rotor and bearings.",
        locator="3",
    )
    login("alpha", "alpha@example.com")

    result = _ask(ids["claim_id"], "Was cavitation confirmed by metallurgical analysis?")

    assert result["status"] == "insufficient_evidence"
    assert result["answer"] == "No sufficient evidence found in the searched claim-file passages."
    assert result["statements"] == []
    assert result["conflicts"] == []
    assert result["missing_evidence"] == ["source-linked claim-file passage supporting the question"]
    assert result["claim_facts_updated"] is False


def test_grounded_qa_surfaces_explicit_conflict_without_reconciliation() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="Workshop_A.txt",
        document_type="workshop_report",
        text="The turbocharger overhaul was completed before the casualty and the rotor was returned to service.",
        locator="2",
    )
    _add_processed_document(
        claim_id=claim_id,
        filename="Survey_B.txt",
        document_type="survey_report",
        text="The turbocharger overhaul was not completed before the casualty; the rotor remained under workshop review.",
        locator="6",
    )
    login("alpha", "alpha@example.com")

    result = _ask(ids["claim_id"], "Was the turbocharger overhaul completed before the casualty?")

    assert result["status"] == "conflicting_evidence"
    assert len(result["statements"]) == 2
    assert result["conflicts"]
    assert result["conflicts"][0]["conflict_type"] == "explicit_polarity"
    assert len(result["conflicts"][0]["statement_hashes"]) == 2
    assert "has not resolved the conflict" in result["answer"]
    assert result["claim_facts_updated"] is False


def test_grounded_qa_is_deterministic_read_only_and_question_is_not_persisted() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="Engine_Log.txt",
        document_type="engine_log",
        text="Evidence records 14,250 turbocharger running hours before casualty.",
        locator="9",
    )
    login("alpha", "alpha@example.com")
    question = "What were the turbocharger operating hours before casualty?"

    with TestingSessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(ClaimFact).where(ClaimFact.claim_id == claim_id)) or 0

    first = _ask(ids["claim_id"], question)
    second = _ask(ids["claim_id"], question)

    assert first["retrieval_run_id"] != second["retrieval_run_id"]
    assert first["question_hash"] == second["question_hash"]
    assert first["result_set_hash"] == second["result_set_hash"]
    assert first["answer_hash"] == second["answer_hash"]
    assert first["answer"] == second["answer"]

    with TestingSessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(ClaimFact).where(ClaimFact.claim_id == claim_id)) or 0
        runs = list(
            db.scalars(
                select(ClaimEvidenceSearchRun)
                .where(ClaimEvidenceSearchRun.claim_id == claim_id)
                .order_by(ClaimEvidenceSearchRun.created_at.asc())
            )
        )
        assert after == before
        assert len(runs) == 2
        for run in runs:
            assert question not in str(run.filters)
            assert question not in str(run.result_ledger)
            assert len(run.normalized_query_hash) == 64

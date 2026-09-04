from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.documents import service as document_service
from app.modules.documents.models import Document, DocumentMalwareScanStatus, DocumentProcessingStatus
from app.modules.rules.requirement_lineage import ClaimDocumentRequirementDecision
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _set_status(claim_id: str, status: ClaimStatus) -> None:
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        assert claim is not None
        claim.status = status
        db.commit()


def _add_maker_fact(claim_id: str, value=12000) -> str:
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        assert claim is not None
        fact = ClaimFact(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            field_path="maintenance.recommended_overhaul_interval",
            value=value,
            source_extraction_id=uuid4(),
            source_document_id=uuid4(),
            source_segment_id=None,
            approved_by_id=None,
            version=1,
        )
        db.add(fact)
        db.commit()
        db.refresh(fact)
        return str(fact.id)


def _evaluate(claim_id: str) -> dict:
    response = client.post(f"/api/v1/claims/{claim_id}/rules/evaluate")
    assert response.status_code == 200, response.text
    return response.json()["summary"]


def _maker_requirement(summary: dict) -> dict:
    return next(row for row in summary["requirements"] if row["document_type"] == "maker_recommendation")


def _candidate(requirement: dict, fact_id: str | None = None) -> dict:
    rows = requirement["equivalent_evidence_candidates"]
    if fact_id is None:
        assert len(rows) == 1
        return rows[0]
    return next(row for row in rows if row["claim_fact_id"] == fact_id)


def _payload(requirement: dict, candidate: dict, note: str, *, re_review: bool = False, fact_version: int | None = None) -> dict:
    return {
        "claim_fact_id": candidate["claim_fact_id"],
        "claim_fact_version": fact_version if fact_version is not None else candidate["claim_fact_version"],
        "expected_state_fingerprint": requirement["state_fingerprint"],
        "expected_state_version": requirement["state_version"],
        "note": note,
        "re_review": re_review,
    }


def _accept(claim_id: str, requirement: dict, candidate: dict, note: str, *, re_review: bool = False, fact_version: int | None = None):
    return client.post(
        f"/api/v1/claims/{claim_id}/rules/requirements/{requirement['id']}/accept-equivalent",
        json=_payload(requirement, candidate, note, re_review=re_review, fact_version=fact_version),
    )


def _seed_equivalent_claim() -> tuple[str, str, dict, dict]:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    fact_id = _add_maker_fact(claim_id)
    summary = _evaluate(claim_id)
    requirement = _maker_requirement(summary)
    candidate = _candidate(requirement, fact_id)
    assert requirement["state_fingerprint"] and requirement["state_version"] >= 1
    assert candidate["claim_fact_version"] == 1
    return claim_id, fact_id, requirement, candidate


def test_initial_acceptance_creates_append_only_decision_and_history() -> None:
    claim_id, _, requirement, candidate = _seed_equivalent_claim()
    response = _accept(
        claim_id,
        requirement,
        candidate,
        "Reviewed canonical maker interval as sufficient equivalent evidence.",
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    decision = payload["decision"]
    assert payload["requirement"]["status"] == "accepted"
    assert payload["requirement"]["latest_decision"]["id"] == decision["id"]
    assert decision["decision_number"] == 1
    assert decision["claim_fact_version"] == 1
    assert decision["previous_decision_hash"] is None
    assert len(decision["decision_hash"]) == 64

    history = client.get(
        f"/api/v1/claims/{claim_id}/rules/requirements/{requirement['id']}/decisions"
    )
    assert history.status_code == 200, history.text
    assert [row["id"] for row in history.json()["items"]] == [decision["id"]]


def test_exact_transport_replay_is_idempotent() -> None:
    claim_id, _, requirement, candidate = _seed_equivalent_claim()
    note = "Reviewed canonical maker interval as sufficient equivalent evidence."
    first = _accept(claim_id, requirement, candidate, note)
    assert first.status_code == 200, first.text
    second = _accept(claim_id, requirement, candidate, note)
    assert second.status_code == 200, second.text
    assert second.json()["decision"]["id"] == first.json()["decision"]["id"]

    with TestingSessionLocal() as db:
        rows = list(
            db.scalars(
                select(ClaimDocumentRequirementDecision).where(
                    ClaimDocumentRequirementDecision.requirement_id == UUID(requirement["id"])
                )
            )
        )
        assert len(rows) == 1


def test_changed_same_state_decision_requires_deliberate_rereview_and_hash_chains() -> None:
    claim_id, _, requirement, candidate = _seed_equivalent_claim()
    first = _accept(
        claim_id,
        requirement,
        candidate,
        "Initial reviewed equivalent-evidence acceptance.",
    )
    assert first.status_code == 200, first.text

    changed = _accept(
        claim_id,
        requirement,
        candidate,
        "Second human review with a materially different justification.",
    )
    assert changed.status_code == 409
    assert "deliberate re-review" in changed.json()["detail"].lower()

    rereviewed = _accept(
        claim_id,
        requirement,
        candidate,
        "Second human review with a materially different justification.",
        re_review=True,
    )
    assert rereviewed.status_code == 200, rereviewed.text
    second = rereviewed.json()["decision"]
    assert second["decision_number"] == 2
    assert second["previous_decision_hash"] == first.json()["decision"]["decision_hash"]
    assert second["decision_hash"] != first.json()["decision"]["decision_hash"]


def test_requirement_state_change_rejects_stale_human_write() -> None:
    claim_id, fact_id, requirement, candidate = _seed_equivalent_claim()
    with TestingSessionLocal() as db:
        fact = db.get(ClaimFact, UUID(fact_id))
        assert fact is not None
        fact.value = 12500
        fact.version += 1
        db.commit()

    stale = _accept(
        claim_id,
        requirement,
        candidate,
        "Attempt based on the previously displayed evidence state.",
    )
    assert stale.status_code == 409
    assert "evidence state changed" in stale.json()["detail"].lower()


def test_current_requirement_state_rejects_stale_claim_fact_version() -> None:
    claim_id, fact_id, _, _ = _seed_equivalent_claim()
    with TestingSessionLocal() as db:
        fact = db.get(ClaimFact, UUID(fact_id))
        assert fact is not None
        fact.value = 12500
        fact.version += 1
        db.commit()

    current = _maker_requirement(_evaluate(claim_id))
    current_candidate = _candidate(current, fact_id)
    assert current_candidate["claim_fact_version"] == 2
    stale_fact = _accept(
        claim_id,
        current,
        current_candidate,
        "Attempt using a stale canonical fact version after refreshing requirement state.",
        fact_version=1,
    )
    assert stale_fact.status_code == 409
    assert "claimfact changed" in stale_fact.json()["detail"].lower()


def test_accepted_equivalent_becomes_superseded_when_reviewed_fact_changes() -> None:
    claim_id, fact_id, requirement, candidate = _seed_equivalent_claim()
    accepted = _accept(
        claim_id,
        requirement,
        candidate,
        "Reviewed canonical maker interval as sufficient equivalent evidence.",
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["requirement"]["status"] == "accepted"

    with TestingSessionLocal() as db:
        fact = db.get(ClaimFact, UUID(fact_id))
        assert fact is not None
        fact.value = 13000
        fact.version += 1
        db.commit()

    refreshed = _evaluate(claim_id)
    current = _maker_requirement(refreshed)
    assert current["status"] == "superseded"
    assert current["satisfaction_basis"] == "equivalent_evidence_stale"
    assert current["latest_decision"]["decision_number"] == 1
    assert refreshed["readiness"]["important_missing_count"] == 1


def test_direct_document_can_take_over_and_deletion_restores_valid_prior_equivalent(tmp_path: Path) -> None:
    claim_id, _, requirement, candidate = _seed_equivalent_claim()
    accepted = _accept(
        claim_id,
        requirement,
        candidate,
        "Reviewed canonical maker interval as interim equivalent evidence.",
    )
    assert accepted.status_code == 200, accepted.text

    document_service.settings.local_storage_path = str(tmp_path / "documents")
    document_service.settings.max_upload_mb = 1
    uploaded = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        files={"file": ("maker.pdf", b"%PDF-1.4\nMaker interval\n%%EOF", "application/pdf")},
        data={"document_type": "maker_recommendation", "confidentiality_level": "confidential"},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = UUID(uploaded.json()["id"])
    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        document.processing_status = DocumentProcessingStatus.PROCESSED
        document.malware_scan_status = DocumentMalwareScanStatus.CLEAN
        db.commit()

    direct = _maker_requirement(_evaluate(claim_id))
    assert direct["status"] == "under_review"
    assert direct["satisfaction_basis"] == "direct_document"
    assert direct["equivalent_claim_fact_id"] is None
    assert direct["latest_decision"]["decision_number"] == 1

    deleted = client.delete(f"/api/v1/claims/{claim_id}/documents/{document_id}")
    assert deleted.status_code == 204, deleted.text
    restored = _maker_requirement(_evaluate(claim_id))
    assert restored["status"] == "accepted"
    assert restored["satisfaction_basis"] == "equivalent_evidence"
    assert restored["equivalent_claim_fact_id"] == candidate["claim_fact_id"]
    assert restored["latest_decision"]["decision_number"] == 1


def test_requirement_decision_history_is_tenant_scoped() -> None:
    claim_id, _, requirement, candidate = _seed_equivalent_claim()
    accepted = _accept(
        claim_id,
        requirement,
        candidate,
        "Reviewed canonical maker interval as sufficient equivalent evidence.",
    )
    assert accepted.status_code == 200, accepted.text

    client.cookies.clear()
    login("beta", "beta-handler@example.com")
    history = client.get(
        f"/api/v1/claims/{claim_id}/rules/requirements/{requirement['id']}/decisions"
    )
    assert history.status_code == 404

from sqlalchemy import func, select

from app.modules.claims.facts import ClaimFact
from app.modules.intelligence.models import DocumentExtraction
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claim_intake import approval_payload, login, seed, upload_and_process


def setup_function() -> None:
    client.cookies.clear()
    reset_database()


def test_human_approved_intake_facts_use_real_text_lineage_without_fake_ai_rows(
    tmp_path,
    monkeypatch,
) -> None:
    ids = seed()
    login("alpha", "alpha@example.com")
    draft = upload_and_process(tmp_path, monkeypatch)
    payload = approval_payload(ids["alpha_vessel"], draft["extracted_fields"])

    approved = client.post(
        f"/api/v1/claim-intake/drafts/{draft['id']}/approve",
        json=payload,
    )
    assert approved.status_code == 200, approved.text
    claim_id = approved.json()["claim"]["id"]
    source_document_id = approved.json()["draft"]["source_document_id"]

    response = client.get(f"/api/v1/claims/{claim_id}/facts")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 9
    facts = {item["field_path"]: item for item in response.json()["items"]}

    assert set(facts) == {
        "claim.vessel_id",
        "claim.incident_date",
        "claim.notification_date",
        "claim.incident_description",
        "claim.external_reference",
        "claim.claim_type",
        "claim.claim_subtype",
        "claim.priority",
        "claim.currency",
    }
    text_extraction_ids = {item["source_text_extraction_id"] for item in facts.values()}
    assert len(text_extraction_ids) == 1
    assert None not in text_extraction_ids
    for fact in facts.values():
        assert fact["provenance_kind"] == "intake_review"
        assert fact["source_extraction_id"] is None
        assert fact["source_document_id"] == source_document_id
        assert fact["version"] == 1

    # Direct extracted evidence may cite a segment only when the approved value
    # still equals the deterministic candidate and the quote is present there.
    assert facts["claim.incident_date"]["source_segment_id"] is not None
    assert facts["claim.notification_date"]["source_segment_id"] is not None
    assert facts["claim.external_reference"]["source_segment_id"] is not None
    assert facts["claim.priority"]["source_segment_id"] is None
    assert facts["claim.currency"]["source_segment_id"] is None
    assert facts["claim.vessel_id"]["source_segment_id"] is None

    with TestingSessionLocal() as db:
        assert db.scalar(select(func.count(DocumentExtraction.id))) == 0
        assert db.scalar(select(func.count(DocumentTextExtraction.id))) == 1
        assert db.scalar(select(func.count(DocumentTextSegment.id))) >= 1
        assert db.scalar(select(func.count(ClaimFact.id))) == 9

    # The normal approval endpoint short-circuits an already-approved draft and
    # must not duplicate facts or increment their versions.
    repeated = client.post(
        f"/api/v1/claim-intake/drafts/{draft['id']}/approve",
        json=payload,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["claim"]["id"] == claim_id
    with TestingSessionLocal() as db:
        stored = list(db.scalars(select(ClaimFact).order_by(ClaimFact.field_path)))
        assert len(stored) == 9
        assert {fact.version for fact in stored} == {1}


def test_human_edited_intake_value_keeps_document_lineage_but_not_false_segment_lineage(
    tmp_path,
    monkeypatch,
) -> None:
    ids = seed()
    login("alpha", "alpha@example.com")
    draft = upload_and_process(tmp_path, monkeypatch)
    payload = approval_payload(ids["alpha_vessel"], draft["extracted_fields"])
    corrected_description = (
        "Human review corrected the notification: turbocharger vibration was observed "
        "during manoeuvring rather than during the voyage."
    )
    payload["claim"]["incident_description"] = corrected_description

    approved = client.post(
        f"/api/v1/claim-intake/drafts/{draft['id']}/approve",
        json=payload,
    )
    assert approved.status_code == 200, approved.text
    claim_id = approved.json()["claim"]["id"]
    response = client.get(f"/api/v1/claims/{claim_id}/facts")
    assert response.status_code == 200
    facts = {item["field_path"]: item for item in response.json()["items"]}

    description = facts["claim.incident_description"]
    assert description["value"] == corrected_description
    assert description["provenance_kind"] == "intake_review"
    assert description["source_extraction_id"] is None
    assert description["source_text_extraction_id"] is not None
    assert description["source_document_id"] == approved.json()["draft"]["source_document_id"]
    assert description["source_segment_id"] is None

    # Unedited directly-supported values retain their verified segment citation.
    assert facts["claim.incident_date"]["source_segment_id"] is not None


def test_intake_claim_facts_remain_tenant_scoped(tmp_path, monkeypatch) -> None:
    ids = seed()
    login("alpha", "alpha@example.com")
    draft = upload_and_process(tmp_path, monkeypatch)
    approved = client.post(
        f"/api/v1/claim-intake/drafts/{draft['id']}/approve",
        json=approval_payload(ids["alpha_vessel"], draft["extracted_fields"]),
    )
    assert approved.status_code == 200
    claim_id = approved.json()["claim"]["id"]

    client.cookies.clear()
    login("beta", "beta@example.com")
    hidden = client.get(f"/api/v1/claims/{claim_id}/facts")
    assert hidden.status_code == 404

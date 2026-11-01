"""Synthetic-only independent OCR observation; NOT scanner accuracy or pilot approval."""
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.claims.facts import ClaimFact
from app.modules.documents.models import Document, DocumentMalwareScanStatus
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentTextExtraction
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_document_processing import PASSWORD, login
from tests.test_ocr_discrepancy_observations import _setup


def setup_function() -> None:
    reset_database()


def _add_manager(org: str, email: str) -> None:
    with TestingSessionLocal() as db:
        tenant = db.scalar(select(Organization).where(Organization.slug == org))
        assert tenant is not None
        db.add(User(
            organization_id=tenant.id,
            email=email,
            full_name="Fictional independent OCR manager",
            password_hash=hash_password(PASSWORD),
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        ))
        db.commit()


def _review_path(report_url: str, report_id: str) -> str:
    return f"{report_url}/{report_id}/independent-reviews"


def _payload(source: dict) -> dict:
    return {
        "source_file_hash": source["source_file_hash"],
        "extraction_text_hash": source["extraction_text_hash"],
        "reviewer_compared_original_scan": True,
        "review_method": "visual_original_scan",
        "outcome": "inconclusive",
        "review_workpaper_sha256": "c" * 64,
    }


def test_independent_manager_observation_is_append_only_and_never_clears_source_hold(
    tmp_path, monkeypatch,
) -> None:
    ids, doc_id, source, url = _setup(tmp_path, monkeypatch)
    report = client.post(url, json=source)
    assert report.status_code == 201, report.text
    report_id = report.json()["id"]
    review_url = _review_path(url, report_id)

    # Initial reporter is a handler, not an independent authorized manager.
    assert client.post(review_url, json=_payload(source)).status_code == 403
    _add_manager("alpha", "independent@example.com")
    client.cookies.clear()
    login("alpha", "independent@example.com")
    result = client.post(review_url, json=_payload(source))
    assert result.status_code == 201, result.text
    receipt = result.json()
    assert result.headers["cache-control"] == "no-store"
    assert receipt["report_id"] == report_id
    assert receipt["document_id"] == doc_id
    assert receipt["review_method"] == "visual_original_scan"
    assert receipt["outcome"] == "inconclusive"
    assert receipt["review_state"] == "independent_observation_no_clearance"
    assert receipt["source_hold_cleared"] is False
    assert receipt["claim_fact_approved"] is False
    assert "source_text" not in receipt
    assert "correction" not in receipt

    # Exact retry is idempotent, not a fresh independent attestation.
    replay = client.post(review_url, json=_payload(source))
    assert replay.status_code == 200, replay.text
    assert replay.json() == receipt
    listed = client.get(review_url)
    assert listed.status_code == 200, listed.text
    assert listed.headers["cache-control"] == "no-store"
    assert listed.json()["items"] == [receipt]
    assert client.get(review_url, params={"limit": 0}).status_code == 422
    assert client.get(review_url, params={"offset": -1}).status_code == 422

    # Even a manager assertion of "not reproduced" must NOT clear the
    # original complaint or human-approved source-revalidation warnings.
    other = client.post(review_url, json={
        **_payload(source),
        "outcome": "not_reproduced",
        "review_workpaper_sha256": "d" * 64,
    })
    assert other.status_code == 201, other.text
    assert other.json()["id"] != receipt["id"]

    history = client.get(f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports")
    assert history.status_code == 200, history.text
    assert history.json()["current_unverified_ocr_source_report_count"] == 1
    client.cookies.clear()
    login("alpha", "alpha@example.com")
    assert client.get(review_url).json()["items"][0]["source_hold_cleared"] is False
    with TestingSessionLocal() as db:
        audit = list(db.scalars(select(AuditLog).where(
            AuditLog.organization_id == UUID(ids["alpha_org"]),
            AuditLog.entity_id == UUID(doc_id),
        )))
        assert len([x for x in audit if x.action == "REPORT_OCR_SOURCE_DISCREPANCY"]) == 1
        observed = [x for x in audit if x.action == "REVIEW_OCR_SOURCE_DISCREPANCY_INDEPENDENT"]
        assert len(observed) == 2
        assert all(x.user_id != UUID(report.json()["reported_by_id"]) for x in observed)
        assert db.scalar(select(func.count()).select_from(ClaimFact).where(
            ClaimFact.claim_id == UUID(ids["claim_id"]),
        )) == 0


def test_independent_observation_refuses_self_review_mismatches_and_foreign_tenant(
    tmp_path, monkeypatch,
) -> None:
    ids, doc_id, source, url = _setup(tmp_path, monkeypatch)
    report = client.post(url, json=source)
    assert report.status_code == 201
    review_url = _review_path(url, report.json()["id"])

    # Even when the reporter is promoted, a one-person "independent" review is forbidden.
    with TestingSessionLocal() as db:
        reporter = db.scalar(select(User).where(User.email == "alpha@example.com"))
        reporter.role = UserRole.CLAIMS_MANAGER
        db.commit()
    assert client.post(review_url, json=_payload(source)).status_code == 403

    _add_manager("alpha", "manager2@example.com")
    client.cookies.clear()
    login("alpha", "manager2@example.com")
    for invalid in (
        {"reviewer_compared_original_scan": False},
        {"review_method": "machine_only"},
        {"outcome": "source_verified"},
        {"review_workpaper_sha256": "not-a-hash"},
        {"extra_claim_approved": True},
    ):
        bad = client.post(review_url, json={**_payload(source), **invalid})
        assert bad.status_code == 422, bad.text
    for stale in (
        {"source_file_hash": "f" * 64},
        {"extraction_text_hash": "e" * 64},
    ):
        assert client.post(review_url, json={**_payload(source), **stale}).status_code == 409
    assert client.post(_review_path(url, str(uuid4())), json=_payload(source)).status_code == 404

    _add_manager("beta", "beta-manager@example.com")
    client.cookies.clear()
    login("beta", "beta-manager@example.com")
    assert client.get(review_url).status_code == 404
    assert client.post(review_url, json=_payload(source)).status_code == 404

    client.cookies.clear()
    login("alpha", "manager2@example.com")
    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(doc_id))
        doc.malware_scan_status = DocumentMalwareScanStatus.LEGACY_UNSCANNED
        db.commit()
    assert client.post(review_url, json=_payload(source)).status_code == 409
    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(doc_id))
        doc.malware_scan_status = DocumentMalwareScanStatus.CLEAN
        extraction = db.scalar(select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == UUID(doc_id),
        ))
        extraction.text_hash = "a" * 64
        db.commit()
    assert client.post(review_url, json={
        **_payload(source), "extraction_text_hash": "a" * 64,
    }).status_code == 409
    with TestingSessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "REVIEW_OCR_SOURCE_DISCREPANCY_INDEPENDENT",
        )) == 0



def test_independent_review_never_reapproves_older_human_approved_ai_claim_fact() -> None:
    """Approval chronology and disputed source state survive a later second opinion."""
    from tests.test_ocr_discrepancy_historical_fact_revalidation import (
        _get_facts, _setup_ocr_reviewed_fact,
    )

    ids, source = _setup_ocr_reviewed_fact()
    before = _get_facts(ids)
    assert before["approved_at"] is not None
    url = (
        f"/api/v1/claims/{ids['claim_id']}/documents/{ids['document_id']}"
        "/processing/source-discrepancies"
    )
    reported = client.post(url, json=source)
    assert reported.status_code == 201, reported.text
    review_url = _review_path(url, reported.json()["id"])
    first_stale = _get_facts(ids)
    assert first_stale["source_revalidation_required"] is True

    # A second authorized human documents a contrary observation.
    _add_manager("alpha", "independent2@example.com")
    client.cookies.clear()
    login("alpha", "independent2@example.com")
    contrary = client.post(review_url, json={
        **_payload(source),
        "outcome": "not_reproduced",
        "review_workpaper_sha256": "d" * 64,
    })
    assert contrary.status_code == 201, contrary.text
    assert contrary.json()["source_hold_cleared"] is False

    after = _get_facts(ids)
    assert after["source_revalidation_required"] is True
    assert after["source_revalidation_reason"] == "source_ocr_discrepancy_reported_unverified"
    for immutable in (
        "id", "value", "version", "approved_by_id",
        "approved_at", "source_extraction_id",
    ):
        assert after[immutable] == before[immutable]
    packs = client.get(f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports")
    assert packs.status_code == 200
    assert packs.json()["current_unverified_ocr_source_report_count"] == 1

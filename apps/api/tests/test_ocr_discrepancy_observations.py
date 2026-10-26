"""Synthetic-only, audit-backed human OCR discrepancy observations.

The fixture uses a DOCX worker extraction whose method is relabeled OCR
*in the test database* to exercise API authorization. It is NOT a Persian
OCR accuracy test, real source review, or proof of any human validation.
"""
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.modules.audit.models import AuditLog
from app.modules.claims.facts import ClaimFact
from app.modules.documents.models import Document, DocumentMalwareScanStatus
from app.modules.processing.models import DocumentTextExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_document_processing import configure_storage, login, seed_claim
from tests.test_unverified_source_segments import (
    _fake_clean_malware_scan, _run_worker, _upload,
)


def setup_function() -> None:
    reset_database()


def _setup(tmp_path, monkeypatch) -> tuple[dict[str, str], str, dict, str]:
    _fake_clean_malware_scan(monkeypatch)
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    doc_id = _upload(ids["claim_id"])
    _run_worker()
    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(doc_id))
        extraction = db.scalar(select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == UUID(doc_id),
        ))
        assert doc is not None and extraction is not None
        assert doc.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        # Test authorization state, not real OCR results.
        extraction.extraction_method = "tesseract:eng+fas"
        db.commit()
        payload = {
            "document_version": doc.version_number,
            "source_file_hash": doc.file_hash,
            "extraction_text_hash": extraction.text_hash,
            "segment_index": 0,
            "issue_kind": "negation_missing",
            "source_compared_by_operator": True,
        }
    return ids, doc_id, payload, (
        f"/api/v1/claims/{ids['claim_id']}/documents/{doc_id}/"
        "processing/source-discrepancies"
    )


def test_reports_append_audit_only_without_approving_claim_facts(tmp_path, monkeypatch) -> None:
    ids, doc_id, payload, url = _setup(tmp_path, monkeypatch)
    result = client.post(url, json=payload)
    assert result.status_code == 201, result.text
    assert result.headers["cache-control"] == "no-store"
    receipt = result.json()
    assert receipt["document_id"] == doc_id
    assert receipt["document_version"] == 1
    assert receipt["source_file_hash"] == payload["source_file_hash"]
    assert receipt["extraction_text_hash"] == payload["extraction_text_hash"]
    assert receipt["segment_index"] == 0
    assert receipt["locator_type"] == "document"
    assert receipt["locator_value"] == "body"
    assert receipt["issue_kind"] == "negation_missing"
    assert receipt["review_state"] == "reported_unverified"
    assert receipt["claim_fact_approved"] is False
    assert receipt["reported_by_id"]
    assert receipt["reported_at"]
    assert "text" not in receipt
    assert "correction" not in receipt

    listed = client.get(url)
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "no-store"
    assert listed.json()["offset"] == 0
    assert listed.json()["items"] == [receipt]
    assert client.get(url, params={"offset": 1}).json()["items"] == []
    assert client.get(url, params={"limit": 0}).status_code == 422
    assert client.get(url, params={"limit": 26}).status_code == 422
    assert client.get(url, params={"offset": -1}).status_code == 422

    with TestingSessionLocal() as db:
        audits = list(db.scalars(select(AuditLog).where(
            AuditLog.organization_id == UUID(ids["alpha_org"]),
            AuditLog.entity_id == UUID(doc_id),
            AuditLog.action == "REPORT_OCR_SOURCE_DISCREPANCY",
        )))
        assert len(audits) == 1
        data = audits[0].new_values
        assert data["source_compared_by_operator"] is True
        assert data["review_state"] == "reported_unverified"
        assert data["claim_fact_approved"] is False
        assert data["issue_kind"] == "negation_missing"
        assert "text_preview" not in data
        assert "corrected_text" not in data
        assert db.scalar(select(func.count()).select_from(ClaimFact).where(
            ClaimFact.claim_id == UUID(ids["claim_id"]),
        )) == 0


def test_report_requires_exact_current_hashes_and_checked_source(tmp_path, monkeypatch) -> None:
    ids, doc_id, payload, url = _setup(tmp_path, monkeypatch)
    for tamper in (
        {"source_compared_by_operator": False},
        {"issue_kind": "source_verified"},
        {"extra_approval": True},
        {"document_version": 0},
        {"source_file_hash": "not a hash"},
    ):
        assert client.post(url, json={**payload, **tamper}).status_code == 422
    for stale in (
        {"document_version": 2},
        {"source_file_hash": "a" * 64},
        {"extraction_text_hash": "b" * 64},
        {"segment_index": 999},
    ):
        assert client.post(url, json={**payload, **stale}).status_code == 409

    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(doc_id))
        assert doc is not None
        doc.is_current = False
        db.commit()
    assert client.post(url, json=payload).status_code == 409
    with TestingSessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "REPORT_OCR_SOURCE_DISCREPANCY",
        )) == 0


def test_ocr_discrepancy_is_tenant_isolated_and_fail_closed(tmp_path, monkeypatch) -> None:
    _, doc_id, payload, url = _setup(tmp_path, monkeypatch)
    assert client.get(url).status_code == 200
    client.cookies.clear()
    login("beta", "beta@example.com")
    assert client.get(url).status_code == 404
    assert client.post(url, json=payload).status_code == 404
    wrong_claim_url = url.replace(url.split("/claims/")[1].split("/documents/")[0], str(uuid4()))
    assert client.get(wrong_claim_url).status_code == 404

    client.cookies.clear()
    login("alpha", "alpha@example.com")
    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(doc_id))
        assert doc is not None
        doc.malware_scan_status = DocumentMalwareScanStatus.LEGACY_UNSCANNED
        db.commit()
    assert client.get(url).status_code == 409
    assert client.post(url, json=payload).status_code == 409

    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(doc_id))
        assert doc is not None
        doc.malware_scan_status = DocumentMalwareScanStatus.CLEAN
        extraction = db.scalar(select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == UUID(doc_id)
        ))
        assert extraction is not None
        extraction.extraction_method = "python-docx"
        db.commit()
    assert client.get(url).status_code == 409
    assert client.post(url, json=payload).status_code == 409

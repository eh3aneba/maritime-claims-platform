"""Read-only machine extraction access is not OCR accuracy certification.

Runs on a tiny invented DOCX fixture through the actual processing worker.
No real scans, reviewer authorization or production transcript in logs.
"""
from uuid import UUID, uuid4

from sqlalchemy import select

from app.modules.documents import service as document_service
from app.modules.documents.malware import MalwareScanResult, MalwareScanVerdict
from app.modules.documents.models import Document, DocumentMalwareScanStatus
from app.modules.processing.models import DocumentTextSegment
from app.modules.processing.service import claim_next_job, process_job
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_document_processing import (
    configure_storage,
    login,
    make_docx_bytes,
    seed_claim,
)


def setup_function() -> None:
    reset_database()


def _fake_clean_malware_scan(monkeypatch) -> list[str]:
    """Only synthetic unit-test upload gets a stubbed clean scanner verdict.

    Do not weaken the actual API's CLEAN-only source read guard. The real
    browser E2E still uses ClamAV; no real scan is claimed by this unit test.
    """
    scanned: list[str] = []

    def synthetic_verdict(path, **kwargs):
        del kwargs
        assert path.is_file()
        scanned.append(str(path))
        return MalwareScanResult(verdict=MalwareScanVerdict.CLEAN)

    monkeypatch.setattr(document_service.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(document_service, "scan_file", synthetic_verdict)
    return scanned


def _upload(claim_id: str) -> str:
    response = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        files={
            "file": (
                "synthetic-engineer.docx",
                make_docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"document_type": "chief_engineer_report"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _run_worker() -> None:
    with TestingSessionLocal() as db:
        job = claim_next_job(db, worker_id="synthetic-source-review-test")
        assert job is not None
        process_job(db, job=job)


def test_source_segments_are_tenant_scoped_machine_unverified_and_read_only(
    tmp_path, monkeypatch
) -> None:
    scanned = _fake_clean_malware_scan(monkeypatch)
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    document_id = _upload(ids["claim_id"])
    assert len(scanned) == 1
    with TestingSessionLocal() as db:
        source = db.get(Document, UUID(document_id))
        assert source is not None
        assert source.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        assert source.malware_scanned_at is not None
    url = f"/api/v1/claims/{ids['claim_id']}/documents/{document_id}/processing/source-segments"

    before = client.get(url)
    assert before.status_code == 409
    _run_worker()

    result = client.get(url)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    body = result.json()
    assert body["document_id"] == document_id
    assert body["document_version"] == 1
    assert len(body["source_file_hash"]) == 64
    assert len(body["extraction_text_hash"]) == 64
    assert body["extraction_method"] == "python-docx"
    assert body["source_text_quality_state"] == "not_an_ocr_extraction"
    assert body["review_disposition"] == "machine_unverified"
    assert body["total_segments"] == 1
    assert body["offset"] == 0
    assert body["limit"] == 5
    assert len(body["segments"]) == 1
    segment = body["segments"][0]
    assert segment["segment_index"] == 0
    assert segment["locator_type"] == "document"
    assert segment["locator_value"] == "body"
    assert "abnormal turbocharger vibration" in segment["text_preview"]
    assert segment["source_char_count"] == len(segment["text_preview"])
    assert segment["text_truncated"] is False
    assert not any("verified" in key or "approved" in key for key in segment)
    assert set(body) == {
        "document_id", "document_version", "source_file_hash", "extraction_text_hash",
        "extraction_method", "source_text_quality_state", "review_disposition",
        "total_segments", "offset", "limit", "segments",
    }
    out_of_bounds = client.get(url, params={"offset": 1, "limit": 1})
    assert out_of_bounds.status_code == 200
    assert out_of_bounds.json()["segments"] == []
    for query in ({"offset": -1}, {"limit": 0}, {"limit": 6}):
        invalid = client.get(url, params=query)
        assert invalid.status_code == 422

    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(document_id))
        assert doc is not None
        assert doc.processing_status.value == "processed"

    client.cookies.clear()
    login("beta", "beta@example.com")
    assert client.get(url).status_code == 404
    assert client.get(
        f"/api/v1/claims/{uuid4()}/documents/{document_id}/processing/source-segments"
    ).status_code == 404


def test_source_segments_deny_unclean_documents_and_label_bounded_previews(
    tmp_path, monkeypatch
) -> None:
    scanned = _fake_clean_malware_scan(monkeypatch)
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    document_id = _upload(ids["claim_id"])
    assert len(scanned) == 1
    _run_worker()
    url = f"/api/v1/claims/{ids['claim_id']}/documents/{document_id}/processing/source-segments"
    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(document_id))
        assert doc is not None
        doc.malware_scan_status = DocumentMalwareScanStatus.LEGACY_UNSCANNED
        db.commit()
    assert client.get(url).status_code == 409

    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(document_id))
        assert doc is not None
        doc.malware_scan_status = DocumentMalwareScanStatus.CLEAN
        segment = db.scalar(select(DocumentTextSegment).where(
            DocumentTextSegment.document_id == UUID(document_id),
        ))
        assert segment is not None
        segment.text = "x" * 12_010
        segment.char_count = len(segment.text)
        db.commit()

    result = client.get(url)
    assert result.status_code == 200, result.text
    row = result.json()["segments"][0]
    assert len(row["text_preview"]) == 12_000
    assert row["source_char_count"] == 12_010
    assert row["text_truncated"] is True
    assert result.json()["review_disposition"] == "machine_unverified"


def test_unscanned_document_stays_denied_even_after_extraction(tmp_path, monkeypatch) -> None:
    """Processing success must not silently upgrade legacy-unscanned custody."""
    monkeypatch.setattr(document_service.settings, "malware_scan_enabled", False)
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    document_id = _upload(ids["claim_id"])
    url = f"/api/v1/claims/{ids['claim_id']}/documents/{document_id}/processing/source-segments"
    _run_worker()
    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(document_id))
        assert document is not None
        assert document.malware_scan_status == DocumentMalwareScanStatus.LEGACY_UNSCANNED
        assert document.processing_status.value == "processed"
    denied = client.get(url)
    assert denied.status_code == 409
    assert denied.json()["detail"] == (
        "Clean, processed, authorized evidence is required for source comparison"
    )

"""Synthetic-only managed workpaper linkage for OCR independent reviewer.
The uploaded DOCX is invented; this does not test Persian OCR or certify review.
"""
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

from docx import Document as WordDocument
from sqlalchemy import func, select

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document, DocumentMalwareScanStatus
from app.modules.processing.models import DocumentTextExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_document_processing import login
from tests.test_ocr_discrepancy_observations import _setup
from tests.test_ocr_discrepancy_independent_review import (
    _add_manager, _payload, _review_path,
)


def setup_function() -> None:
    reset_database()


def _upload_workpaper(claim_id: str) -> dict:
    sample = WordDocument()
    sample.add_heading("FICTIONAL OCR review workpaper", level=1)
    sample.add_paragraph("Invented original-scan comparison training note; not verified.")
    data = BytesIO()
    sample.save(data)
    raw = data.getvalue()
    result = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        files={"file": (
            "synthetic-ocr-workpaper.docx", raw,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )},
        data={"document_type": "ocr_review_workpaper"},
    )
    assert result.status_code == 201, result.text
    row = result.json()
    assert row["file_hash"] == sha256(raw).hexdigest()
    assert row["malware_scan_status"] == "clean"
    return row


def _prepare(tmp_path, monkeypatch):
    ids, doc_id, source, url = _setup(tmp_path, monkeypatch)
    report = client.post(url, json=source)
    assert report.status_code == 201, report.text
    report_id = report.json()["id"]
    _add_manager("alpha", "reviewer@example.com")
    client.cookies.clear()
    login("alpha", "reviewer@example.com")
    workpaper = _upload_workpaper(ids["claim_id"])
    review = client.post(
        _review_path(url, report_id),
        json={**_payload(source), "review_workpaper_sha256": workpaper["file_hash"]},
    )
    assert review.status_code == 201, review.text
    path = _review_path(url, report_id) + f"/{review.json()['id']}/workpaper-binding"
    payload = {
        "workpaper_document_id": workpaper["id"],
        "workpaper_file_hash": workpaper["file_hash"],
    }
    return ids, doc_id, source, report_id, review.json(), workpaper, path, payload


def test_managed_clean_workpaper_link_has_exact_hash_and_never_clears_ocr_dispute(
    tmp_path, monkeypatch,
) -> None:
    ids, doc_id, source, report_id, review, workpaper, path, payload = _prepare(
        tmp_path, monkeypatch,
    )
    assert client.get(path).status_code == 404
    linked = client.post(path, json=payload)
    assert linked.status_code == 201, linked.text
    receipt = linked.json()
    assert linked.headers["cache-control"] == "no-store"
    assert receipt["report_id"] == report_id
    assert receipt["review_id"] == review["id"]
    assert receipt["document_id"] == doc_id
    assert receipt["workpaper_document_id"] == workpaper["id"]
    assert receipt["workpaper_document_version"] == 1
    assert receipt["workpaper_file_hash"] == workpaper["file_hash"]
    assert receipt["custody_state"] == "managed_clean_document_record_linked"
    assert receipt["original_source_hold_cleared"] is False
    assert receipt["claim_fact_approved"] is False
    assert "workpaper_text" not in receipt and "approved_value" not in receipt

    replay = client.post(path, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json() == receipt
    read = client.get(path)
    assert read.status_code == 200
    assert read.json() == receipt
    assert read.headers["cache-control"] == "no-store"
    pack = client.get(f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports")
    assert pack.status_code == 200
    assert pack.json()["current_unverified_ocr_source_report_count"] == 1
    with TestingSessionLocal() as db:
        entries = list(db.scalars(select(AuditLog).where(
            AuditLog.action == "BIND_OCR_INDEPENDENT_REVIEW_WORKPAPER",
        )))
        assert len(entries) == 1
        assert entries[0].new_values["original_source_hold_cleared"] is False
        assert entries[0].new_values["source_file_hash"] == source["source_file_hash"]
        assert entries[0].new_values["extraction_text_hash"] == source["extraction_text_hash"]


def test_historical_workpaper_receipt_readback_survives_ocr_reprocessing_and_supersession(
    tmp_path, monkeypatch,
) -> None:
    ids, doc_id, source, report_id, review, workpaper, path, payload = _prepare(
        tmp_path, monkeypatch,
    )
    linked = client.post(path, json=payload)
    assert linked.status_code == 201, linked.text
    receipt = linked.json()

    with TestingSessionLocal() as db:
        extraction = db.scalar(select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == UUID(doc_id),
        ))
        assert extraction is not None
        extraction.text_hash = "e" * 64
        db.commit()

    # GET is an immutable historic receipt, not re-admission against
    # the currently different OCR transcript. POST must still fail closed.
    historical = client.get(path)
    assert historical.status_code == 200, historical.text
    assert historical.json() == receipt
    assert historical.headers["cache-control"] == "no-store"
    assert client.post(path, json=payload).status_code == 409

    with TestingSessionLocal() as db:
        original = db.get(Document, UUID(doc_id))
        workpaper_document = db.get(Document, UUID(workpaper["id"]))
        assert original is not None and workpaper_document is not None
        original.is_current = False
        workpaper_document.is_current = False
        db.commit()
    after_supersession = client.get(path)
    assert after_supersession.status_code == 200, after_supersession.text
    assert after_supersession.json() == receipt
    assert client.post(path, json=payload).status_code == 409

    # Tenant isolation and original-file identity are not relaxed for GET.
    client.cookies.clear()
    login("beta", "beta@example.com")
    assert client.get(path).status_code == 404
    client.cookies.clear()
    login("alpha", "reviewer@example.com")
    with TestingSessionLocal() as db:
        original = db.get(Document, UUID(doc_id))
        original.file_hash = "f" * 64
        db.commit()
    assert client.get(path).status_code == 409

    with TestingSessionLocal() as db:
        original = db.get(Document, UUID(doc_id))
        original.file_hash = source["source_file_hash"]
        db.commit()
        events = list(db.scalars(select(AuditLog).where(
            AuditLog.action == "BIND_OCR_INDEPENDENT_REVIEW_WORKPAPER",
        )))
        assert len(events) == 1
        assert events[0].new_values["original_source_hold_cleared"] is False
        assert events[0].new_values["claim_fact_approved"] is False
    assert client.get(path).json() == receipt
    pack = client.get(f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports")
    assert pack.status_code == 200
    # Supersession may affect *current* discrepancy counters, but it cannot
    # silently change historical approval or mark this review as verified.
    assert "current_unverified_ocr_source_report_count" in pack.json()


def test_workpaper_historical_get_rejects_cross_linked_or_tampered_metadata(
    tmp_path, monkeypatch,
) -> None:
    _, doc_id, source, _, review, _, path, payload = _prepare(tmp_path, monkeypatch)
    linked = client.post(path, json=payload)
    assert linked.status_code == 201, linked.text
    for key, value in (
        ("extraction_text_hash", "e" * 64),
        ("source_file_hash", "f" * 64),
        ("workpaper_file_hash", "e" * 64),
        ("review_id", str(uuid4())),
        ("original_source_hold_cleared", True),
        ("claim_fact_approved", True),
    ):
        with TestingSessionLocal() as db:
            event = db.scalar(select(AuditLog).where(
                AuditLog.action == "BIND_OCR_INDEPENDENT_REVIEW_WORKPAPER",
            ))
            assert event is not None
            before = dict(event.new_values)
            event.new_values = {**before, key: value}
            db.commit()
        response = client.get(path)
        assert response.status_code == 409, (key, response.text)
        with TestingSessionLocal() as db:
            event = db.scalar(select(AuditLog).where(
                AuditLog.action == "BIND_OCR_INDEPENDENT_REVIEW_WORKPAPER",
            ))
            event.new_values = before
            db.commit()
    assert client.get(path).status_code == 200


def test_workpaper_link_refuses_wrong_hash_source_user_role_tenant_and_unclean_evidence(
    tmp_path, monkeypatch,
) -> None:
    ids, doc_id, source, report_id, review, workpaper, path, payload = _prepare(
        tmp_path, monkeypatch,
    )
    assert client.post(path, json={**payload, "extra_approval": True}).status_code == 422
    assert client.post(path, json={**payload, "workpaper_file_hash": "bad"}).status_code == 422
    assert client.post(path, json={
        **payload, "workpaper_file_hash": "e" * 64,
    }).status_code == 409
    assert client.post(path, json={
        **payload, "workpaper_document_id": doc_id,
    }).status_code == 409
    assert client.post(path, json={
        **payload, "workpaper_document_id": str(uuid4()),
    }).status_code == 404

    client.cookies.clear()
    login("alpha", "alpha@example.com")
    assert client.post(path, json=payload).status_code == 403
    assert client.get(path).status_code == 404

    _add_manager("alpha", "another@example.com")
    client.cookies.clear()
    login("alpha", "another@example.com")
    assert client.post(path, json=payload).status_code == 403

    _add_manager("beta", "beta-reviewer@example.com")
    client.cookies.clear()
    login("beta", "beta-reviewer@example.com")
    assert client.post(path, json=payload).status_code == 404
    assert client.get(path).status_code == 404

    client.cookies.clear()
    login("alpha", "reviewer@example.com")
    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(workpaper["id"]))
        doc.malware_scan_status = DocumentMalwareScanStatus.LEGACY_UNSCANNED
        db.commit()
    assert client.post(path, json=payload).status_code == 409
    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(workpaper["id"]))
        doc.malware_scan_status = DocumentMalwareScanStatus.CLEAN
        doc.document_type = "chief_engineer_report"
        db.commit()
    assert client.post(path, json=payload).status_code == 409
    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(workpaper["id"]))
        doc.document_type = "ocr_review_workpaper"
        doc.is_current = False
        db.commit()
    assert client.post(path, json=payload).status_code == 409
    with TestingSessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "BIND_OCR_INDEPENDENT_REVIEW_WORKPAPER",
        )) == 0

"""Synthetic-only read-side disclosure after an OCR discrepancy report.

Existing approved facts and assessment hashes remain historical records.
A report is an unverified operator concern, not a corrected scan or an
independently verified error, and may not authorize automatic adjudication.
"""
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID

from openpyxl import load_workbook
from pypdf import PdfReader

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.claim_packs.recovery_renderers import render_pdf, render_xlsx
from app.modules.claim_packs.recovery_service import build_claim_pack_snapshot
from app.modules.claims.models import Claim
from app.modules.users.models import User
from app.modules.assessments.models import InitialAssessment
from app.modules.claims.facts import ClaimFact
from app.modules.documents.models import Document, DocumentMalwareScanStatus
from app.modules.intelligence.models import AIReviewStatus, DocumentExtraction
from app.modules.processing.models import AI_SOURCE_REPROCESSED_WARNING, DocumentTextExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_human_ai_review import login, seed_review_candidates


def setup_function() -> None:
    reset_database()


def _setup_ocr_reviewed_fact() -> tuple[dict[str, str], dict]:
    ids = seed_review_candidates()
    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(ids["document_id"]))
        document.malware_scan_status = DocumentMalwareScanStatus.CLEAN
        source = db.scalar(select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == document.id,
        ))
        source.extraction_method = "tesseract:eng+fas"
        db.commit()
        receipt = {
            "document_version": document.version_number,
            "source_file_hash": document.file_hash,
            "extraction_text_hash": source.text_hash,
            "segment_index": 0,
            "issue_kind": "negation_missing",
            "source_compared_by_operator": True,
        }
    login("alpha", "alpha@example.com")
    reviewed = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={
            "action": "approve",
            "reason": "Fictional pre-report operator assertion of original source comparison.",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["promoted"] is True
    return ids, receipt


def _get_facts(ids: dict) -> dict:
    response = client.get(f"/api/v1/claims/{ids['claim_id']}/facts")
    assert response.status_code == 200, response.text
    item = next(v for v in response.json()["items"] if v["field_path"] == "equipment.maker")
    return item


def test_later_ocr_report_flags_historical_fact_and_stales_assessment_without_rewriting_either() -> None:
    ids, payload = _setup_ocr_reviewed_fact()
    before_fact = _get_facts(ids)
    assert before_fact["source_revalidation_required"] is False
    assert before_fact["source_revalidation_reason"] is None
    before_assessment = client.post(
        f"/api/v1/claims/{ids['claim_id']}/initial-assessment/generate",
        json={
            "allow_if_not_ready": True,
            "override_reason": "Fictional source-sensitive assessment; no independent human approval.",
        },
    )
    assert before_assessment.status_code == 200, before_assessment.text
    old = before_assessment.json()
    assert old["source_state"] == "current"
    assert old["source_fingerprint"]
    with TestingSessionLocal() as db:
        historical = db.get(InitialAssessment, UUID(old["id"]))
        assert historical is not None
        assert "reported_ocr_source_discrepancies" not in historical.source_snapshot["sources"]

    url = (
        f"/api/v1/claims/{ids['claim_id']}/documents/{ids['document_id']}"
        "/processing/source-discrepancies"
    )
    submitted = client.post(url, json=payload)
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["review_state"] == "reported_unverified"
    latest_fact = _get_facts(ids)
    assert latest_fact["source_revalidation_required"] is True
    assert latest_fact["source_revalidation_reason"] == "source_ocr_discrepancy_reported_unverified"
    for preserved in ("id", "value", "version", "approved_by_id", "approved_at", "source_extraction_id"):
        assert latest_fact[preserved] == before_fact[preserved]

    stale = client.get(
        f"/api/v1/claims/{ids['claim_id']}/initial-assessment/versions/{old['id']}"
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["source_state"] == "stale"
    assert stale.json()["source_fingerprint"] == old["source_fingerprint"]
    assert stale.json()["current_source_fingerprint"] != old["source_fingerprint"]
    blocked = client.post(
        f"/api/v1/claims/{ids['claim_id']}/initial-assessment/sections/{old['sections'][0]['id']}/review",
        json={
            "action": "approve",
            "expected_source_fingerprint": old["source_fingerprint"],
        },
    )
    assert blocked.status_code == 409, blocked.text

    with TestingSessionLocal() as db:
        fact = db.get(ClaimFact, UUID(before_fact["id"]))
        extraction = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assessment = db.get(InitialAssessment, UUID(old["id"]))
        assert fact.value == "ABB"
        assert extraction.human_status == AIReviewStatus.APPROVED
        assert assessment.source_fingerprint == old["source_fingerprint"]
        assert assessment.status.value == "draft"
        source = db.scalar(select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == UUID(ids["document_id"]),
        ))
        source.text_hash = "d" * 64
        extraction.validation_warnings = [AI_SOURCE_REPROCESSED_WARNING]
        db.commit()
    # Reprocessing the SAME original source cannot outrank/clear its dispute.
    after_reprocess = _get_facts(ids)
    assert after_reprocess["source_revalidation_required"] is True
    assert after_reprocess["source_revalidation_reason"] == "source_ocr_discrepancy_reported_unverified"


def test_mismatched_or_foreign_tenant_reports_do_not_mark_fact_stale() -> None:
    ids, payload = _setup_ocr_reviewed_fact()
    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(ids["document_id"]))
        from app.modules.organizations.models import Organization
        beta = db.scalar(select(Organization).where(Organization.slug == "beta"))
        fake_values = {
            "claim_id": ids["claim_id"], "document_version": document.version_number,
            "source_file_hash": "f" * 64,
            "review_state": "reported_unverified",
        }
        db.add(AuditLog(
            organization_id=document.organization_id,
            action="REPORT_OCR_SOURCE_DISCREPANCY",
            entity_type="document",
            entity_id=document.id,
            new_values=fake_values,
        ))
        db.add(AuditLog(
            organization_id=beta.id,
            action="REPORT_OCR_SOURCE_DISCREPANCY",
            entity_type="document",
            entity_id=document.id,
            new_values={**fake_values, "source_file_hash": document.file_hash},
        ))
        db.commit()
    assert _get_facts(ids)["source_revalidation_required"] is False
    baseline = client.post(
        f"/api/v1/claims/{ids['claim_id']}/initial-assessment/generate",
        json={
            "allow_if_not_ready": True,
            "override_reason": "No source-matched report and no independent approval.",
        },
    )
    assert baseline.status_code == 200, baseline.text
    assert baseline.json()["source_state"] == "current"


def test_later_ocr_discrepancy_is_disclosed_in_new_pdf_xlsx_claim_pack() -> None:
    """A historical AI fact must not appear source-clean on exported handoff."""
    ids, payload = _setup_ocr_reviewed_fact()
    url = (
        f"/api/v1/claims/{ids['claim_id']}/documents/{ids['document_id']}"
        "/processing/source-discrepancies"
    )
    reported = client.post(url, json=payload)
    assert reported.status_code == 201, reported.text

    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(ids["claim_id"]))
        assert claim is not None
        user = db.scalar(select(User).where(
            User.organization_id == claim.organization_id,
            User.email == "alpha@example.com",
        ))
        assert user is not None
        snapshot = build_claim_pack_snapshot(
            db,
            claim=claim,
            user=user,
            generation_note="Fictional source dispute; not expert adjudication",
            generated_at=datetime(2026, 10, 31, 10, 0, tzinfo=UTC),
        )

    assert snapshot["summary"]["review_state"] == "attention_required"
    assert snapshot["summary"]["approved_ai_fact_source_revalidation_count"] == 1
    flagged = snapshot["approved_ai_fact_source_revalidation"]
    assert len(flagged) == 1
    assert flagged[0] == {
        "field_path": "equipment.maker",
        "source_document_id": ids["document_id"],
        "reason": "source_ocr_discrepancy_reported_unverified",
    }

    pdf = PdfReader(BytesIO(render_pdf(snapshot)))
    content = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "source_ocr_discrepancy_reported_unverified" in content
    assert "no automatic reversal or reapproval" in content

    workbook = load_workbook(BytesIO(render_xlsx(snapshot)), read_only=True)
    try:
        rows = list(workbook["AI Fact Source Review"].values)
        assert rows[1][1] == 1
        assert rows[5][0] == "equipment.maker"
        assert rows[5][1] == ids["document_id"]
        assert rows[5][2] == "source_ocr_discrepancy_reported_unverified"
        summary = dict(list(workbook["Pack Summary"].values)[1:])
        assert summary["Review state"] == "attention_required"
        assert summary["Previously approved AI facts requiring source revalidation"] == 1
    finally:
        workbook.close()

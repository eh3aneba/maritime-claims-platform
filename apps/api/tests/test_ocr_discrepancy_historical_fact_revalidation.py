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


def test_new_assessment_cannot_launder_unverified_ocr_fact_source_dispute() -> None:
    """New fingerprint includes allegation but does not make it source-clean."""
    ids, payload = _setup_ocr_reviewed_fact()
    # This fixture starts in NEW; move to INVESTIGATION before generating
    # either snapshot so the manager-approval test exercises the OCR hold,
    # not the independent NEW-claim readiness restriction.
    from app.modules.claims.models import ClaimStatus
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(ids["claim_id"]))
        assert claim is not None
        claim.status = ClaimStatus.INVESTIGATION
        db.commit()
    base = f"/api/v1/claims/{ids['claim_id']}/initial-assessment"
    old_response = client.post(f"{base}/generate", json={
        "allow_if_not_ready": True,
        "override_reason": "Fictional pre-report baseline for source-control validation.",
    })
    assert old_response.status_code == 200, old_response.text
    old = old_response.json()
    assert old["unverified_ocr_fact_source_review_hold"] is False

    reported = client.post(
        f"/api/v1/claims/{ids['claim_id']}/documents/{ids['document_id']}"
        "/processing/source-discrepancies",
        json=payload,
    )
    assert reported.status_code == 201, reported.text
    assert reported.json()["review_state"] == "reported_unverified"

    new_response = client.post(f"{base}/generate", json={
        "allow_if_not_ready": True,
        "override_reason": "A new source fingerprint is not human source adjudication.",
    })
    assert new_response.status_code == 200, new_response.text
    new = new_response.json()
    # The new snapshot is fresh relative to the *reported* allegation,
    # but the earlier approved AI fact in that snapshot is still disputed.
    assert new["source_state"] == "current"
    assert new["unverified_ocr_fact_source_review_hold"] is True
    assert new["source_fingerprint"] != old["source_fingerprint"]
    historical = client.get(f"{base}/versions/{old['id']}")
    assert historical.status_code == 200
    assert historical.json()["source_state"] == "stale"
    assert historical.json()["unverified_ocr_fact_source_review_hold"] is True

    # An unrelated or superseded fact snapshot must not acquire the hold
    # through a reused current canonical fact ID with a different row hash.
    from types import SimpleNamespace
    from app.modules.assessments.source_integrity import (
        assessment_unverified_ocr_fact_review_hold,
    )
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(ids["claim_id"]))
        fact = db.scalar(select(ClaimFact).where(
            ClaimFact.organization_id == claim.organization_id,
            ClaimFact.claim_id == claim.id,
            ClaimFact.field_path == "equipment.maker",
        ))
        assert fact is not None
        fake_old_version = SimpleNamespace(source_snapshot={
            "sources": {"claim_facts": [
                {"id": str(fact.id), "row_hash": "0" * 64}
            ]},
        })
        assert not assessment_unverified_ocr_fact_review_hold(
            db, claim=claim, assessment=fake_old_version,
        )

    history = client.get(f"{base}/history")
    assert history.status_code == 200, history.text
    assert [item["unverified_ocr_fact_source_review_hold"]
            for item in history.json()["items"]] == [True, True]
    assert [item["source_state"] for item in history.json()["items"]] == [
        "current", "stale",
    ]

    blocked_review = client.post(
        f"{base}/sections/{new['sections'][0]['id']}/review",
        json={"action": "approve", "expected_source_fingerprint": new["source_fingerprint"]},
    )
    assert blocked_review.status_code == 409, blocked_review.text
    assert "Unresolved operator-reported OCR source discrepancy" in blocked_review.text

    # Elevate the fictional user for the manager-only approval route. The
    # server must reject an attempt even when the version fingerprint is fresh.
    from app.modules.users.models import UserRole
    with TestingSessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "alpha@example.com"))
        assert user is not None
        user.role = UserRole.CLAIMS_MANAGER
        db.commit()
    login("alpha", "alpha@example.com")
    blocked_approval = client.post(
        f"{base}/{new['id']}/approve",
        json={"expected_source_fingerprint": new["source_fingerprint"]},
    )
    assert blocked_approval.status_code == 409, blocked_approval.text
    assert "Unresolved operator-reported OCR source discrepancy" in blocked_approval.text

    unchanged = _get_facts(ids)
    assert unchanged["value"] == "ABB"
    assert unchanged["source_revalidation_required"] is True
    with TestingSessionLocal() as db:
        row = db.get(InitialAssessment, UUID(new["id"]))
        assert row.status.value == "draft"
        assert row.approved_at is None
        assert row.approved_content_hash is None


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
    assert baseline.json()["unverified_ocr_fact_source_review_hold"] is False
    history = client.get(f"/api/v1/claims/{ids['claim_id']}/initial-assessment/history")
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["unverified_ocr_fact_source_review_hold"] is False


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


def test_historical_claim_pack_list_and_download_disclose_later_source_report_without_mutating_file() -> None:
    """Late operator allegation must be visible on access, not written into archived bytes."""
    ids, receipt = _setup_ocr_reviewed_fact()
    original_fact = _get_facts(ids)
    base_url = f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports"
    generated = client.post(base_url, json={
        "export_format": "xlsx",
        "acknowledge_review_aid": True,
        "generation_note": "Synthetic immutable handoff, before original-source report.",
    })
    assert generated.status_code == 201, generated.text
    export_id = generated.json()["id"]
    download_url = f"{base_url}/{export_id}/download"

    baseline_list = client.get(base_url)
    assert baseline_list.status_code == 200, baseline_list.text
    assert baseline_list.json()["total"] == 1
    assert baseline_list.json()["current_unverified_ocr_source_report_count"] == 0
    original_download = client.get(download_url)
    assert original_download.status_code == 200, original_download.text
    header = "X-Claim-Current-Unverified-OCR-Source-Report-Count"
    assert original_download.headers[header] == "0"
    saved_snapshot_hash = original_download.headers["X-Claim-Pack-Snapshot-SHA256"]
    saved_file_hash = original_download.headers["X-Claim-Pack-File-SHA256"]
    saved_bytes = original_download.content

    report = client.post(
        f"/api/v1/claims/{ids['claim_id']}/documents/{ids['document_id']}"
        "/processing/source-discrepancies",
        json=receipt,
    )
    assert report.status_code == 201, report.text
    assert report.json()["review_state"] == "reported_unverified"

    updated_list = client.get(base_url)
    assert updated_list.status_code == 200, updated_list.text
    assert updated_list.json()["total"] == 1
    assert updated_list.json()["items"] == baseline_list.json()["items"]
    assert updated_list.json()["current_unverified_ocr_source_report_count"] == 1
    original_again = client.get(download_url)
    assert original_again.status_code == 200, original_again.text
    assert original_again.headers[header] == "1"
    assert original_again.headers["X-Claim-Pack-Snapshot-SHA256"] == saved_snapshot_hash
    assert original_again.headers["X-Claim-Pack-File-SHA256"] == saved_file_hash
    assert original_again.content == saved_bytes
    assert _get_facts(ids)["id"] == original_fact["id"]
    assert _get_facts(ids)["approved_at"] == original_fact["approved_at"]


def test_historical_claim_pack_notice_ignores_wrong_hash_and_foreign_tenant_receipts() -> None:
    """Only source-matched current documents in this claim influence advisory count."""
    ids, _ = _setup_ocr_reviewed_fact()
    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(ids["document_id"]))
        from app.modules.organizations.models import Organization
        beta = db.scalar(select(Organization).where(Organization.slug == "beta"))
        assert beta is not None
        report = {
            "claim_id": ids["claim_id"],
            "document_version": document.version_number,
            "source_file_hash": document.file_hash,
            "review_state": "reported_unverified",
        }
        db.add(AuditLog(
            organization_id=document.organization_id,
            action="REPORT_OCR_SOURCE_DISCREPANCY",
            entity_type="document",
            entity_id=document.id,
            new_values={**report, "source_file_hash": "f" * 64},
        ))
        db.add(AuditLog(
            organization_id=beta.id,
            action="REPORT_OCR_SOURCE_DISCREPANCY",
            entity_type="document",
            entity_id=document.id,
            new_values=report,
        ))
        db.commit()
    listed = client.get(f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports")
    assert listed.status_code == 200, listed.text
    assert listed.json()["current_unverified_ocr_source_report_count"] == 0

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.chronology.models import ChronologyMateriality, ConflictStatus, EvidenceConflict
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentProcessingStatus
from app.modules.intelligence.models import (
    AIFeedback,
    AIRun,
    AIRunStatus,
    AISemanticKind,
    AIReviewStatus,
    DocumentExtraction,
)
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database

PASSWORD = "Strong-Review-Test-2026"


def setup_function() -> None:
    reset_database()


def login(slug: str, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"organization_slug": slug, "email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def seed_review_candidates() -> dict[str, str]:
    with TestingSessionLocal() as db:
        alpha = Organization(name="Alpha Marine", slug="alpha")
        beta = Organization(name="Beta Marine", slug="beta")
        db.add_all([alpha, beta])
        db.flush()
        alpha_user = User(
            organization_id=alpha.id,
            email="alpha@example.com",
            full_name="Alpha Handler",
            password_hash=hash_password(PASSWORD),
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        beta_user = User(
            organization_id=beta.id,
            email="beta@example.com",
            full_name="Beta Handler",
            password_hash=hash_password(PASSWORD),
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        vessel = Vessel(organization_id=alpha.id, name="MT ORION", imo_number="7000301")
        db.add_all([alpha_user, beta_user, vessel])
        db.flush()
        claim = Claim(
            organization_id=alpha.id,
            vessel_id=vessel.id,
            claim_reference="MCRI-HM-2026-0001",
            incident_date=date(2026, 7, 10),
            notification_date=date(2026, 7, 11),
            incident_description="Turbocharger failure",
            currency="USD",
        )
        db.add(claim)
        db.flush()
        document = Document(
            organization_id=alpha.id,
            claim_id=claim.id,
            uploaded_by_id=alpha_user.id,
            filename="server-ce.docx",
            original_filename="CE_Report.docx",
            document_type="chief_engineer_report",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_size_bytes=1024,
            file_hash="a" * 64,
            storage_key=f"{alpha.id}/{claim.id}/ce.docx",
            version_number=1,
            processing_status=DocumentProcessingStatus.PROCESSED,
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )
        db.add(document)
        db.flush()
        text_extraction = DocumentTextExtraction(
            organization_id=alpha.id,
            document_id=document.id,
            extraction_method="python-docx",
            extractor_version="1.0",
            char_count=180,
            segment_count=1,
            requires_ocr=False,
            text_hash="b" * 64,
        )
        db.add(text_extraction)
        db.flush()
        segment = DocumentTextSegment(
            organization_id=alpha.id,
            document_id=document.id,
            extraction_id=text_extraction.id,
            segment_index=0,
            locator_type="document",
            locator_value="body",
            text="MT ORION Chief Engineer report. Turbocharger maker ABB. Incident alarm at 10:30 UTC. I suspect bearing damage caused the failure.",
            char_count=126,
        )
        db.add(segment)
        db.flush()
        run = AIRun(
            organization_id=alpha.id,
            claim_id=claim.id,
            document_id=document.id,
            requested_by_id=alpha_user.id,
            task="chief_engineer_report_extract",
            status=AIRunStatus.COMPLETED,
            provider="fake",
            model="fake-v1",
            prompt_name="ce_report",
            prompt_version="1.0",
            schema_name="chief_engineer_report_v1",
            schema_version="1.0",
            input_text_hash="c" * 64,
            input_char_count=126,
            document_type_candidate="chief_engineer_report",
            classification_confidence=Decimal("0.980"),
        )
        db.add(run)
        db.flush()
        maker = DocumentExtraction(
            organization_id=alpha.id,
            claim_id=claim.id,
            document_id=document.id,
            ai_run_id=run.id,
            source_segment_id=segment.id,
            field_path="equipment.maker",
            semantic_kind=AISemanticKind.FACT,
            raw_value="ABB",
            normalized_value="ABB",
            confidence=Decimal("0.970"),
            source_locator_type="document",
            source_locator_value="body",
            source_quote="Turbocharger maker ABB",
            source_verified=True,
            human_status=AIReviewStatus.PENDING,
        )
        incident_time = DocumentExtraction(
            organization_id=alpha.id,
            claim_id=claim.id,
            document_id=document.id,
            ai_run_id=run.id,
            source_segment_id=segment.id,
            field_path="incident.time",
            semantic_kind=AISemanticKind.FACT,
            raw_value="10:30",
            normalized_value="10:30",
            confidence=Decimal("0.960"),
            source_locator_type="document",
            source_locator_value="body",
            source_quote="Incident alarm at 10:30 UTC",
            source_verified=True,
            human_status=AIReviewStatus.PENDING,
        )
        opinion = DocumentExtraction(
            organization_id=alpha.id,
            claim_id=claim.id,
            document_id=document.id,
            ai_run_id=run.id,
            source_segment_id=segment.id,
            field_path="suspected_cause_opinions[0]",
            semantic_kind=AISemanticKind.OPINION,
            raw_value="bearing damage",
            normalized_value="bearing damage",
            confidence=Decimal("0.930"),
            source_locator_type="document",
            source_locator_value="body",
            source_quote="I suspect bearing damage caused the failure",
            source_verified=True,
            human_status=AIReviewStatus.PENDING,
        )
        unverified = DocumentExtraction(
            organization_id=alpha.id,
            claim_id=claim.id,
            document_id=document.id,
            ai_run_id=run.id,
            source_segment_id=segment.id,
            field_path="equipment.model",
            semantic_kind=AISemanticKind.FACT,
            raw_value="VTR-500",
            normalized_value="VTR-500",
            confidence=Decimal("0.920"),
            source_locator_type="document",
            source_locator_value="body",
            source_quote="VTR-500",
            source_verified=False,
            validation_warnings=["Source quote could not be verified."],
            human_status=AIReviewStatus.PENDING,
        )
        db.add_all([maker, incident_time, opinion, unverified])
        db.commit()
        return {
            "claim_id": str(claim.id),
            "document_id": str(document.id),
            "maker_id": str(maker.id),
            "time_id": str(incident_time.id),
            "opinion_id": str(opinion.id),
            "unverified_id": str(unverified.id),
            "alpha_org_id": str(alpha.id),
        }


def test_review_queue_exposes_source_and_bulk_eligibility() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    response = client.get("/api/v1/ai-review")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 4
    by_id = {row["extraction_id"]: row for row in payload["items"]}
    assert by_id[ids["maker_id"]]["bulk_approvable"] is True
    assert by_id[ids["time_id"]]["bulk_approvable"] is False
    assert by_id[ids["opinion_id"]]["semantic_kind"] == "opinion"
    assert by_id[ids["maker_id"]]["claim_reference"] == "MCRI-HM-2026-0001"
    assert by_id[ids["maker_id"]]["document_name"] == "CE_Report.docx"


def test_approve_fact_promotes_to_claim_fact_and_writes_feedback() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    response = client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["human_status"] == "approved"
    assert payload["approved_value"] == "ABB"
    assert payload["promoted"] is True
    assert payload["claim_fact"]["field_path"] == "equipment.maker"
    assert payload["claim_fact"]["value"] == "ABB"

    with TestingSessionLocal() as db:
        extraction = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assert extraction.human_status == AIReviewStatus.APPROVED
        fact = db.scalar(select(ClaimFact).where(ClaimFact.source_extraction_id == extraction.id))
        assert fact is not None and fact.value == "ABB"
        feedback = list(db.scalars(select(AIFeedback).where(AIFeedback.extraction_id == extraction.id)))
        assert len(feedback) == 1
        assert feedback[0].action == "approved"
        audit = list(db.scalars(select(AuditLog).where(AuditLog.organization_id == extraction.organization_id)))
        assert any(row.action == "REVIEW_AI_EXTRACTION" and row.entity_id == extraction.id for row in audit)
        assert any(row.action == "CREATE_APPROVED_CLAIM_FACT" for row in audit)


def test_edit_fact_preserves_ai_value_and_promotes_human_value() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    response = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "edit", "value": "ABB Turbo Systems", "reason": "Full maker name shown in header."},
    )
    assert response.status_code == 200
    assert response.json()["human_status"] == "edited"
    assert response.json()["claim_fact"]["value"] == "ABB Turbo Systems"
    with TestingSessionLocal() as db:
        extraction = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        feedback = db.scalar(select(AIFeedback).where(AIFeedback.extraction_id == extraction.id))
        assert feedback.ai_value == "ABB"
        assert feedback.human_value == "ABB Turbo Systems"
        assert extraction.raw_value == "ABB"  # raw AI output remains unchanged


def test_approved_opinion_is_reviewed_but_never_promoted_as_fact() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    response = client.post(f"/api/v1/ai-review/{ids['opinion_id']}", json={"action": "approve"})
    assert response.status_code == 200
    assert response.json()["human_status"] == "approved"
    assert response.json()["promoted"] is False
    assert response.json()["claim_fact"] is None
    with TestingSessionLocal() as db:
        facts = list(db.scalars(select(ClaimFact).where(ClaimFact.claim_id == UUID(ids["claim_id"]))))
        assert facts == []


def test_unverified_source_requires_explicit_reason_for_approval() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    denied = client.post(f"/api/v1/ai-review/{ids['unverified_id']}", json={"action": "approve"})
    assert denied.status_code == 409
    assert "reason" in denied.json()["detail"].lower()
    accepted = client.post(
        f"/api/v1/ai-review/{ids['unverified_id']}",
        json={"action": "approve", "reason": "Verified manually against the document page."},
    )
    assert accepted.status_code == 200
    assert accepted.json()["promoted"] is True


def test_rejecting_previously_approved_source_removes_current_claim_fact_but_keeps_history() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    approved = client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
    assert approved.status_code == 200
    rejected = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "reject", "reason": "Later review shows this maker belongs to another unit.", "confirm_re_review": True},
    )
    assert rejected.status_code == 200
    assert rejected.json()["human_status"] == "rejected"
    assert rejected.json()["claim_fact"] is None
    with TestingSessionLocal() as db:
        fact = db.scalar(select(ClaimFact).where(ClaimFact.claim_id == UUID(ids["claim_id"]), ClaimFact.field_path == "equipment.maker"))
        assert fact is None
        feedback = list(db.scalars(select(AIFeedback).where(AIFeedback.extraction_id == UUID(ids["maker_id"]))))
        assert [row.action for row in feedback] == ["approved", "rejected"]


def test_bulk_approve_is_all_or_nothing_and_only_low_risk_verified_high_confidence() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    bad_batch = client.post(
        "/api/v1/ai-review/bulk/approve",
        json={"extraction_ids": [ids["maker_id"], ids["time_id"]]},
    )
    assert bad_batch.status_code == 409
    with TestingSessionLocal() as db:
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assert maker.human_status == AIReviewStatus.PENDING

    good_batch = client.post(
        "/api/v1/ai-review/bulk/approve",
        json={"extraction_ids": [ids["maker_id"]], "reason": "Identity metadata checked."},
    )
    assert good_batch.status_code == 200, good_batch.text
    assert good_batch.json()["reviewed"][0]["human_status"] == "approved"


def test_source_preview_returns_original_segment_and_is_tenant_protected() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    response = client.get(f"/api/v1/ai-review/{ids['time_id']}/source")
    assert response.status_code == 200
    assert "Incident alarm at 10:30 UTC" in response.json()["segment_text"]
    assert response.json()["source_verified"] is True

    client.cookies.clear()
    login("beta", "beta@example.com")
    denied = client.get(f"/api/v1/ai-review/{ids['time_id']}/source")
    assert denied.status_code == 404


def test_review_detail_returns_append_only_feedback_history_and_current_fact() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
    client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "edit", "value": "ABB Turbo Systems", "reason": "Expanded maker name.", "confirm_re_review": True},
    )
    response = client.get(f"/api/v1/ai-review/{ids['maker_id']}")
    assert response.status_code == 200
    payload = response.json()
    assert [row["action"] for row in payload["feedback"]] == ["approved", "edited"]
    assert all(row["reviewer_name"] == "Alpha Handler" for row in payload["feedback"])
    assert payload["current_claim_fact"]["value"] == "ABB Turbo Systems"
    assert payload["current_claim_fact"]["version"] == 2


def test_bulk_approve_rejects_duplicate_ids_before_mutation() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    response = client.post(
        "/api/v1/ai-review/bulk/approve",
        json={"extraction_ids": [ids["maker_id"], ids["maker_id"]]},
    )
    assert response.status_code == 422
    with TestingSessionLocal() as db:
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assert maker.human_status == AIReviewStatus.PENDING


def test_soft_deleted_evidence_cannot_be_reviewed_by_direct_extraction_id() -> None:
    ids = seed_review_candidates()
    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(ids["document_id"]))
        from datetime import UTC, datetime
        document.deleted_at = datetime.now(UTC)
        db.commit()
    login("alpha", "alpha@example.com")
    response = client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
    assert response.status_code == 404


def test_sensitive_fact_path_is_never_promoted_even_if_schema_labels_it_fact() -> None:
    ids = seed_review_candidates()
    with TestingSessionLocal() as db:
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        run_id = maker.ai_run_id
        sensitive = DocumentExtraction(
            organization_id=maker.organization_id,
            claim_id=maker.claim_id,
            document_id=maker.document_id,
            ai_run_id=run_id,
            source_segment_id=maker.source_segment_id,
            field_path="coverage.decision",
            semantic_kind=AISemanticKind.FACT,
            raw_value="covered",
            normalized_value="covered",
            confidence=Decimal("0.990"),
            source_locator_type=maker.source_locator_type,
            source_locator_value=maker.source_locator_value,
            source_quote=maker.source_quote,
            source_verified=True,
            human_status=AIReviewStatus.PENDING,
        )
        db.add(sensitive)
        db.commit()
        sensitive_id = sensitive.id
    login("alpha", "alpha@example.com")
    response = client.post(f"/api/v1/ai-review/{sensitive_id}", json={"action": "approve"})
    assert response.status_code == 200
    assert response.json()["promoted"] is False
    with TestingSessionLocal() as db:
        fact = db.scalar(select(ClaimFact).where(ClaimFact.claim_id == UUID(ids["claim_id"]), ClaimFact.field_path == "coverage.decision"))
        assert fact is None


def test_claim_facts_endpoint_exposes_only_human_approved_facts() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    before = client.get(f"/api/v1/claims/{ids['claim_id']}/facts")
    assert before.status_code == 200
    assert before.json()["total"] == 0
    client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
    client.post(f"/api/v1/ai-review/{ids['opinion_id']}", json={"action": "approve"})
    after = client.get(f"/api/v1/claims/{ids['claim_id']}/facts")
    assert after.status_code == 200
    assert after.json()["total"] == 1
    assert after.json()["items"][0]["field_path"] == "equipment.maker"
    assert after.json()["items"][0]["value"] == "ABB"


def test_review_queue_all_statuses_and_claim_facts_are_tenant_protected() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    assert client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"}).status_code == 200
    pending = client.get("/api/v1/ai-review?review_status=pending")
    all_rows = client.get("/api/v1/ai-review?review_status=all")
    assert pending.status_code == 200 and pending.json()["total"] == 3
    assert all_rows.status_code == 200 and all_rows.json()["total"] == 4

    client.cookies.clear()
    login("beta", "beta@example.com")
    denied = client.get(f"/api/v1/claims/{ids['claim_id']}/facts")
    assert denied.status_code == 404


def test_grouped_review_clusters_engine_log_row_and_approves_atomically() -> None:
    ids = seed_review_candidates()
    with TestingSessionLocal() as db:
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assert maker is not None
        rows = [
            ("engine_log.events[0].time", "10:52", AISemanticKind.FACT, Decimal("0.970")),
            ("engine_log.events[0].rpm", {"value": 620, "unit": "rpm", "raw": "620 rpm"}, AISemanticKind.FACT, Decimal("0.960")),
            ("engine_log.events[0].event_type", "alarm", AISemanticKind.INFERENCE, Decimal("0.910")),
        ]
        created = []
        for field_path, value, kind, confidence in rows:
            ex = DocumentExtraction(
                organization_id=maker.organization_id,
                claim_id=maker.claim_id,
                document_id=maker.document_id,
                ai_run_id=maker.ai_run_id,
                source_segment_id=maker.source_segment_id,
                field_path=field_path,
                semantic_kind=kind,
                raw_value=value,
                normalized_value=value,
                confidence=confidence,
                source_locator_type="document",
                source_locator_value="body",
                source_quote="Incident alarm at 10:30 UTC",
                source_verified=True,
                human_status=AIReviewStatus.PENDING,
            )
            db.add(ex)
            created.append(ex)
        db.commit()
        row_ids = [str(row.id) for row in created]

    login("alpha", "alpha@example.com")
    grouped = client.get("/api/v1/ai-review/groups")
    assert grouped.status_code == 200, grouped.text
    row = next(group for group in grouped.json()["groups"] if group["group_key"] == "engine_log.events[0]")
    assert row["group_type"] == "engine_log_row"
    assert len(row["items"]) == 3
    assert row["needs_attention"] is True  # event_type is an inference and should be exception-first.
    assert "Opinion or inference requires judgment" in row["attention_reasons"]

    reviewed = client.post(
        "/api/v1/ai-review/groups/review",
        json={"extraction_ids": row_ids, "action": "approve", "reason": "Reviewed the complete log row against source."},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert len(reviewed.json()["reviewed"]) == 3
    with TestingSessionLocal() as db:
        states = [db.get(DocumentExtraction, UUID(row_id)).human_status for row_id in row_ids]
        assert states == [AIReviewStatus.APPROVED] * 3
        assert list(db.scalars(select(ClaimFact).where(ClaimFact.claim_id == UUID(ids["claim_id"]), ClaimFact.field_path.like("engine_log.events[%")))) == []


def test_grouped_review_rejects_fields_from_different_rows() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    response = client.post(
        "/api/v1/ai-review/groups/review",
        json={"extraction_ids": [ids["maker_id"], ids["time_id"]], "action": "approve"},
    )
    assert response.status_code == 409
    assert "same review row" in response.json()["detail"].lower()


def test_evidence_matrix_groups_approved_fact_sources_and_open_conflicts() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    approved = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "approve"},
    )
    assert approved.status_code == 200, approved.text

    with TestingSessionLocal() as db:
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        conflict = EvidenceConflict(
            organization_id=maker.organization_id,
            claim_id=maker.claim_id,
            evidence_a_extraction_id=maker.id,
            conflict_key="matrix-maker-conflict",
            conflict_type="content",
            topic="Turbocharger maker",
            description="A later source records a different maker and requires human review.",
            value_a="ABB",
            value_b="MAN",
            materiality=ChronologyMateriality.HIGH,
            status=ConflictStatus.OPEN,
            is_active=True,
        )
        db.add(conflict)
        db.commit()

    response = client.get(
        f"/api/v1/claims/{ids['claim_id']}/evidence-matrix"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["approved_fact_count"] == 1
    assert payload["summary"]["open_conflict_count"] == 1
    assert payload["summary"]["supporting_source_count"] == 1

    row = next(
        item for item in payload["rows"]
        if item["field_path"] == "equipment.maker"
    )
    assert row["fact_value"] == "ABB"
    assert row["status"] == "conflict_open"
    assert row["supporting_evidence"][0]["document_name"] == "CE_Report.docx"
    assert row["supporting_evidence"][0]["document_version"] == 1
    assert row["supporting_evidence"][0]["document_is_current"] is True
    assert row["supporting_evidence"][0]["authoritative"] is True
    assert row["supporting_evidence"][0]["source_quote"] == "Turbocharger maker ABB"
    assert row["conflicting_evidence"][0]["value_b"] == "MAN"

    client.cookies.clear()
    login("beta", "beta@example.com")
    hidden = client.get(
        f"/api/v1/claims/{ids['claim_id']}/evidence-matrix"
    )
    assert hidden.status_code == 404


def test_evidence_matrix_flags_fact_whose_authoritative_source_is_superseded() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    approved = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "approve"},
    )
    assert approved.status_code == 200

    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(ids["document_id"]))
        document.is_current = False
        document.superseded_at = datetime.now(UTC)
        db.commit()

    response = client.get(
        f"/api/v1/claims/{ids['claim_id']}/evidence-matrix"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    row = next(
        item for item in payload["rows"]
        if item["field_path"] == "equipment.maker"
    )
    assert row["status"] == "source_superseded"
    assert row["supporting_evidence"][0]["document_is_current"] is False
    assert payload["summary"]["superseded_fact_source_count"] == 1
    assert payload["summary"]["historical_source_document_count"] == 1


def test_claim_pack_exports_are_controlled_immutable_and_tenant_scoped() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    approved = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "approve"},
    )
    assert approved.status_code == 200, approved.text

    unacknowledged = client.post(
        f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports",
        json={"export_format": "pdf", "acknowledge_review_aid": False},
    )
    assert unacknowledged.status_code == 422

    pdf = client.post(
        f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports",
        json={
            "export_format": "pdf",
            "acknowledge_review_aid": True,
            "generation_note": "Prepared for controlled internal review.",
        },
    )
    assert pdf.status_code == 201, pdf.text
    pdf_row = pdf.json()
    assert pdf_row["export_format"] == "pdf"
    assert pdf_row["mime_type"] == "application/pdf"
    assert len(pdf_row["snapshot_hash"]) == 64
    assert len(pdf_row["file_hash"]) == 64

    pdf_download = client.get(
        f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports/{pdf_row['id']}/download"
    )
    assert pdf_download.status_code == 200, pdf_download.text
    assert pdf_download.content.startswith(b"%PDF-1.4")
    assert (
        pdf_download.headers["x-claim-pack-snapshot-sha256"]
        == pdf_row["snapshot_hash"]
    )
    assert pdf_download.headers["cache-control"] == "private, no-store"

    xlsx = client.post(
        f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports",
        json={"export_format": "xlsx", "acknowledge_review_aid": True},
    )
    assert xlsx.status_code == 201, xlsx.text
    xlsx_row = xlsx.json()
    xlsx_download = client.get(
        f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports/{xlsx_row['id']}/download"
    )
    assert xlsx_download.status_code == 200
    assert xlsx_download.content.startswith(b"PK")
    assert (
        xlsx_download.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    listing = client.get(
        f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports"
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert listing.json()["items"][0]["id"] == xlsx_row["id"]

    client.cookies.clear()
    login("beta", "beta@example.com")
    hidden_list = client.get(
        f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports"
    )
    hidden_download = client.get(
        f"/api/v1/claims/{ids['claim_id']}/claim-pack-exports/{pdf_row['id']}/download"
    )
    assert hidden_list.status_code == 404
    assert hidden_download.status_code == 404


def test_policy_intelligence_extracts_review_candidates_and_never_promotes_claim_facts() -> None:
    ids = seed_review_candidates()
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(ids["claim_id"]))
        user = db.scalar(
            select(User).where(
                User.organization_id == claim.organization_id,
                User.email == "alpha@example.com",
            )
        )
        claim.notification_date = date(2026, 7, 15)
        policy = Document(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            uploaded_by_id=user.id,
            filename="server-policy.pdf",
            original_filename="HM_Policy_Wording.pdf",
            document_type="policy",
            mime_type="application/pdf",
            file_size_bytes=4096,
            file_hash="d" * 64,
            storage_key=f"{claim.organization_id}/{claim.id}/policy.pdf",
            version_number=1,
            processing_status=DocumentProcessingStatus.PROCESSED,
            confidentiality_level=ConfidentialityLevel.RESTRICTED,
        )
        db.add(policy)
        db.flush()
        extracted_text = DocumentTextExtraction(
            organization_id=claim.organization_id,
            document_id=policy.id,
            extraction_method="pypdf",
            extractor_version="1.0",
            char_count=800,
            segment_count=1,
            requires_ocr=False,
            text_hash="e" * 64,
        )
        db.add(extracted_text)
        db.flush()
        policy_text = (
            "Period of Insurance from 2026-01-01 to 2026-06-30. "
            "The agreed value and sum insured is USD 5,000,000. "
            "The deductible is 10% of each and every loss, minimum USD 50,000. "
            "The Assured shall notify Underwriters within 2 days of any occurrence. "
            "Any proceedings must be commenced within 12 months. "
            "This policy is governed by English law. "
            "Disputes shall be referred to arbitration in London. "
            "War risks and seizure are excluded. "
            "Warranted class maintained throughout the policy period. "
            "General Average shall be adjusted under York-Antwerp Rules 1994. "
            "Sue and Labour charges are recoverable subject to this wording."
        )
        segment = DocumentTextSegment(
            organization_id=claim.organization_id,
            document_id=policy.id,
            extraction_id=extracted_text.id,
            segment_index=0,
            locator_type="page",
            locator_value="1",
            text=policy_text,
            char_count=len(policy_text),
        )
        db.add(segment)
        db.commit()
        policy_id = str(policy.id)

    login("alpha", "alpha@example.com")
    extraction = client.post(
        f"/api/v1/claims/{ids['claim_id']}/policy-intelligence/documents/{policy_id}/extract"
    )
    assert extraction.status_code == 201, extraction.text
    payload = extraction.json()
    assert payload["external_ai_used"] is False
    assert payload["review_required"] is True
    assert payload["candidate_count"] >= 9
    assert all(item["human_status"] == "pending" for item in payload["candidates"])
    assert all(item["source_quote"] for item in payload["candidates"])

    for candidate in payload["candidates"]:
        reviewed = client.post(
            f"/api/v1/ai-review/{candidate['extraction_id']}",
            json={"action": "approve"},
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["promoted"] is False

    intelligence = client.get(
        f"/api/v1/claims/{ids['claim_id']}/policy-intelligence"
    )
    assert intelligence.status_code == 200, intelligence.text
    result = intelligence.json()
    assert result["summary"]["reviewed_term_count"] >= 9
    assert result["summary"]["has_policy_period"] is True
    assert result["summary"]["has_insured_value_or_limit"] is True
    assert result["summary"]["has_deductible"] is True
    codes = {item["code"] for item in result["issue_spots"]}
    assert "incident_date_outside_extracted_policy_period" in codes
    assert "possible_notice_timing_issue" in codes
    assert "exclusions_require_applicability_review" in codes
    assert "warranties_require_compliance_review" in codes
    assert "time_limits_require_diarising" in codes
    assert all(
        "coverage conclusion" not in item["title"].lower()
        for item in result["issue_spots"]
    )

    deductible = next(
        item for item in result["terms"] if item["category"] == "deductible"
    )
    assert deductible["value"]["percentage"] == "10"
    assert deductible["value"]["minimum"] == {
        "currency": "USD",
        "amount": "50000",
    }
    assert deductible["source"]["document_name"] == "HM_Policy_Wording.pdf"
    assert deductible["source"]["source_locator_value"] == "1"

    with TestingSessionLocal() as db:
        policy_fact = db.scalar(
            select(ClaimFact).where(
                ClaimFact.claim_id == UUID(ids["claim_id"]),
                ClaimFact.field_path.like("policy.%"),
            )
        )
        assert policy_fact is None
        policy = db.get(Document, UUID(policy_id))
        policy.is_current = False
        policy.superseded_at = datetime.now(UTC)
        db.commit()

    historical = client.get(
        f"/api/v1/claims/{ids['claim_id']}/policy-intelligence"
    )
    assert historical.status_code == 200
    historical_codes = {
        item["code"] for item in historical.json()["issue_spots"]
    }
    assert "reviewed_terms_from_superseded_sources" in historical_codes
    assert historical.json()["summary"]["current_policy_document_count"] == 0

    client.cookies.clear()
    login("beta", "beta@example.com")
    hidden = client.get(
        f"/api/v1/claims/{ids['claim_id']}/policy-intelligence"
    )
    hidden_extract = client.post(
        f"/api/v1/claims/{ids['claim_id']}/policy-intelligence/documents/{policy_id}/extract"
    )
    assert hidden.status_code == 404
    assert hidden_extract.status_code == 404


def test_policy_extraction_requires_policy_classification() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    denied = client.post(
        f"/api/v1/claims/{ids['claim_id']}/policy-intelligence/documents/{ids['document_id']}/extract"
    )
    assert denied.status_code == 409
    assert "classify" in denied.json()["detail"].lower()

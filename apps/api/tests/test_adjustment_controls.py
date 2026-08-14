from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentProcessingStatus
from app.modules.financial.models import CostItem, CostReviewStatus
from app.modules.intelligence.models import AIRun, AIRunStatus
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _seed_cost_schedule() -> tuple[str, list[str]]:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    user = result["seed"]["admin"]
    with TestingSessionLocal() as db:
        claim_uuid = UUID(claim_id)
        stored_user = db.get(type(user), user.id)
        document = Document(
            organization_id=stored_user.organization_id,
            claim_id=claim_uuid,
            uploaded_by_id=stored_user.id,
            filename="invoice.pdf",
            original_filename="invoice.pdf",
            document_type="invoice",
            mime_type="application/pdf",
            file_size_bytes=100,
            file_hash="a" * 64,
            storage_key="adjustment/invoice-a",
            processing_status=DocumentProcessingStatus.PROCESSED,
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )
        quotation = Document(
            organization_id=stored_user.organization_id,
            claim_id=claim_uuid,
            uploaded_by_id=stored_user.id,
            filename="quotation.pdf",
            original_filename="quotation.pdf",
            document_type="quotation",
            mime_type="application/pdf",
            file_size_bytes=100,
            file_hash="b" * 64,
            storage_key="adjustment/quotation-b",
            processing_status=DocumentProcessingStatus.PROCESSED,
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )
        db.add_all([document, quotation])
        db.flush()
        invoice_run = AIRun(
            organization_id=stored_user.organization_id,
            claim_id=claim_uuid,
            document_id=document.id,
            requested_by_id=stored_user.id,
            task="ai_extract_invoice",
            status=AIRunStatus.COMPLETED,
            provider="test",
            model="test",
            prompt_name="invoice",
            prompt_version="1",
            schema_name="invoice",
            schema_version="1",
            input_text_hash="c" * 64,
            input_char_count=100,
        )
        quote_run = AIRun(
            organization_id=stored_user.organization_id,
            claim_id=claim_uuid,
            document_id=quotation.id,
            requested_by_id=stored_user.id,
            task="ai_extract_quotation",
            status=AIRunStatus.COMPLETED,
            provider="test",
            model="test",
            prompt_name="quotation",
            prompt_version="1",
            schema_name="quotation",
            schema_version="1",
            input_text_hash="d" * 64,
            input_char_count=100,
        )
        db.add_all([invoice_run, quote_run])
        db.flush()
        lines = [
            CostItem(
                organization_id=stored_user.organization_id,
                claim_id=claim_uuid,
                document_id=document.id,
                ai_run_id=invoice_run.id,
                line_index=0,
                document_kind="invoice",
                supplier="Turbo Repair Ltd",
                document_number="INV-100",
                description="Turbocharger rotor repair",
                amount=Decimal("1000.00"),
                currency="USD",
                category="Permanent Repair",
                review_status=CostReviewStatus.UNDER_REVIEW,
                source_field_prefix="invoice.line_items[0]",
            ),
            CostItem(
                organization_id=stored_user.organization_id,
                claim_id=claim_uuid,
                document_id=document.id,
                ai_run_id=invoice_run.id,
                line_index=1,
                document_kind="invoice",
                supplier="Turbo Repair Ltd",
                document_number="INV-100",
                description="Technician attendance and testing",
                amount=Decimal("500.00"),
                currency="USD",
                category="Attendance",
                review_status=CostReviewStatus.UNDER_REVIEW,
                source_field_prefix="invoice.line_items[1]",
            ),
            CostItem(
                organization_id=stored_user.organization_id,
                claim_id=claim_uuid,
                document_id=quotation.id,
                ai_run_id=quote_run.id,
                line_index=0,
                document_kind="quotation",
                supplier="Alternative Maker",
                document_number="Q-200",
                description="Complete replacement alternative",
                amount=Decimal("9000.00"),
                currency="USD",
                category="Replacement",
                review_status=CostReviewStatus.UNDER_REVIEW,
                source_field_prefix="quotation.line_items[0]",
            ),
        ]
        db.add_all(lines)
        db.commit()
        for line in lines:
            db.refresh(line)
        return claim_id, [str(line.id) for line in lines]


def test_adjustment_is_versioned_human_reviewed_and_immutable() -> None:
    claim_id, cost_ids = _seed_cost_schedule()
    created = client.post(
        f"/api/v1/claims/{claim_id}/adjustments",
        json={"currency": "usd", "title": "MT ORION – H&M Adjustment Draft"},
    )
    assert created.status_code == 201, created.text
    statement = created.json()
    assert statement["version"] == 1
    assert statement["status"] == "draft"
    assert statement["gross_claimed"] == "1500.00"
    assert len(statement["lines"]) == 2
    assert all(line["cost_item_id"] != cost_ids[2] for line in statement["lines"])

    blocked = client.post(f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/submit")
    assert blocked.status_code == 409
    assert "treatment is pending" in blocked.json()["detail"]

    first, second = statement["lines"]
    updated = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{first['id']}",
        json={
            "treatment": "included",
            "basis": "particular_average",
            "considered_amount": "1000.00",
            "note": "Casualty repair cost supported by reviewed invoice.",
        },
    )
    assert updated.status_code == 200, updated.text
    updated = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{second['id']}",
        json={
            "treatment": "apportioned",
            "basis": "general_average",
            "considered_amount": "300.00",
            "reason": "USD 200 relates to non-common-safety attendance.",
        },
    )
    assert updated.status_code == 200, updated.text
    updated = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}",
        json={
            "deductible_amount": "100.00",
            "deductible_basis": "Policy deductible subject to final wording review.",
            "other_deduction_amount": "50.00",
            "other_deduction_basis": "Agreed residual value credit.",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["gross_considered"] == "1300.00"
    assert updated.json()["net_adjusted"] == "1150.00"

    submitted = client.post(f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "under_review"

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    denied = client.post(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/approve",
        json={"note": "Handler must not approve."},
    )
    assert denied.status_code == 403

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    approved = client.post(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/approve",
        json={"note": "Line treatments, bases and deductions reviewed against the claim file."},
    )
    assert approved.status_code == 200, approved.text
    approved_payload = approved.json()
    assert approved_payload["status"] == "approved"
    assert len(approved_payload["content_hash"]) == 64

    immutable = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}",
        json={"deductible_amount": "0.00"},
    )
    assert immutable.status_code == 409

    with TestingSessionLocal() as db:
        cost = db.get(CostItem, UUID(cost_ids[0]))
        cost.amount = Decimal("9999.00")
        db.commit()
    preserved = client.get(f"/api/v1/claims/{claim_id}/adjustments").json()["items"][0]
    assert preserved["gross_claimed"] == "1500.00"
    assert preserved["lines"][0]["claimed_amount"] == "1000.00"

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == UUID(statement["id"]))))
        assert {"CREATE_ADJUSTMENT_STATEMENT", "SUBMIT_ADJUSTMENT_FOR_REVIEW", "APPROVE_ADJUSTMENT_STATEMENT"}.issubset(actions)


def test_adjustment_rejects_invalid_line_math_and_is_tenant_scoped() -> None:
    claim_id, _ = _seed_cost_schedule()
    statement = client.post(f"/api/v1/claims/{claim_id}/adjustments", json={"currency": "USD"}).json()
    line = statement["lines"][0]
    invalid = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{line['id']}",
        json={
            "treatment": "apportioned",
            "basis": "particular_average",
            "considered_amount": "2000.00",
            "reason": "Invalid amount",
        },
    )
    assert invalid.status_code == 422

    client.cookies.clear()
    login("beta", "beta-handler@example.com")
    assert client.get(f"/api/v1/claims/{claim_id}/adjustments").status_code == 404
    assert client.post(f"/api/v1/claims/{claim_id}/adjustments", json={"currency": "USD"}).status_code == 404

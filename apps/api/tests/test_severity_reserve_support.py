import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.modules.claims.models import Claim, ClaimStatus
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentProcessingStatus
from app.modules.financial.models import (
    CostItem,
    CostReviewStatus,
    FinancialFlag,
    ReserveHistory,
)
from app.modules.financial.service import sync_financial_review
from app.modules.intelligence.models import AIRun, AIRunStatus, AISemanticKind, AIReviewStatus, DocumentExtraction
from app.modules.intelligence.service import TASK_INVOICE, TASK_QUOTATION
from app.modules.severity_reserve.models import SeverityReserveDecision, SeverityReserveSnapshot
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claim_intelligence import _add_fact, _set_status
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _build(claim_id: str) -> dict:
    response = client.post(f"/api/v1/claims/{claim_id}/severity-reserve/build")
    assert response.status_code == 201, response.text
    return response.json()


def _upsert_reviewed_extraction(
    db,
    *,
    run: AIRun,
    document: Document,
    field_path: str,
    value,
) -> None:
    row = db.scalar(
        select(DocumentExtraction).where(
            DocumentExtraction.ai_run_id == run.id,
            DocumentExtraction.field_path == field_path,
        )
    )
    if row is None:
        row = DocumentExtraction(
            organization_id=run.organization_id,
            claim_id=run.claim_id,
            document_id=document.id,
            ai_run_id=run.id,
            field_path=field_path,
            semantic_kind=AISemanticKind.FACT,
            raw_value=value,
            normalized_value=value,
            confidence=Decimal("0.990"),
            source_locator_type="page",
            source_locator_value="1",
            source_quote=str(value) if value is not None else None,
            source_verified=True,
            human_status=AIReviewStatus.APPROVED,
            approved_value=value,
            reviewed_at=datetime.now(UTC),
        )
        db.add(row)
    else:
        row.raw_value = value
        row.normalized_value = value
        row.approved_value = value
        row.human_status = AIReviewStatus.APPROVED
        row.source_verified = True
        row.reviewed_at = datetime.now(UTC)


def _source_document_and_run(
    db,
    *,
    claim: Claim,
    kind: str,
    document_id: UUID | None,
) -> tuple[Document, AIRun, User]:
    user = db.scalar(select(User).where(User.organization_id == claim.organization_id))
    assert user is not None
    task = TASK_QUOTATION if kind == "quotation" else TASK_INVOICE
    document = db.get(Document, document_id) if document_id is not None else None
    if document is None:
        chosen_id = document_id or uuid4()
        digest = hashlib.sha256(str(chosen_id).encode("utf-8")).hexdigest()
        document = Document(
            id=chosen_id,
            organization_id=claim.organization_id,
            claim_id=claim.id,
            uploaded_by_id=user.id,
            filename=f"{kind}-{chosen_id}.pdf",
            original_filename=f"{kind}-{chosen_id}.pdf",
            document_type=kind,
            mime_type="application/pdf",
            file_size_bytes=100,
            file_hash=digest,
            storage_key=f"tests/{digest}",
            processing_status=DocumentProcessingStatus.PROCESSED,
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )
        db.add(document)
        db.flush()

    run = db.scalar(
        select(AIRun).where(
            AIRun.organization_id == claim.organization_id,
            AIRun.claim_id == claim.id,
            AIRun.document_id == document.id,
            AIRun.task == task,
            AIRun.status == AIRunStatus.COMPLETED,
        )
    )
    if run is None:
        run = AIRun(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            document_id=document.id,
            requested_by_id=user.id,
            task=task,
            status=AIRunStatus.COMPLETED,
            provider="fixture",
            model="fixture-financial-v1",
            prompt_name=f"{kind}_fixture",
            prompt_version="1",
            schema_name=f"{kind}_fixture",
            schema_version="1",
            input_text_hash=document.file_hash,
            input_char_count=100,
            completed_at=datetime.now(UTC),
        )
        db.add(run)
        db.flush()
    return document, run, user


def _add_cost(
    claim_id: str,
    *,
    amount: str,
    currency: str,
    status: CostReviewStatus,
    kind: str = "invoice",
    document_id: UUID | None = None,
    line_index: int = 0,
    supplier: str | None = None,
    document_number: str | None = None,
) -> UUID:
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        assert claim is not None
        document, run, user = _source_document_and_run(
            db,
            claim=claim,
            kind=kind,
            document_id=document_id,
        )
        prefix = "quotation" if kind == "quotation" else "invoice"
        number_field = "quotation_number" if kind == "quotation" else "invoice_number"
        date_field = "quotation_date" if kind == "quotation" else "invoice_date"
        supplier_value = supplier or f"{kind.title()} Supplier"
        number_value = document_number or f"{kind.upper()}-{str(document.id)[:8]}"
        _upsert_reviewed_extraction(db, run=run, document=document, field_path=f"{prefix}.supplier", value=supplier_value)
        _upsert_reviewed_extraction(db, run=run, document=document, field_path=f"{prefix}.{number_field}", value=number_value)
        _upsert_reviewed_extraction(db, run=run, document=document, field_path=f"{prefix}.{date_field}", value="2026-07-12")
        _upsert_reviewed_extraction(db, run=run, document=document, field_path=f"{prefix}.currency", value=currency)
        _upsert_reviewed_extraction(db, run=run, document=document, field_path=f"{prefix}.total", value=amount)
        base = f"{prefix}.line_items[{line_index}]"
        _upsert_reviewed_extraction(
            db,
            run=run,
            document=document,
            field_path=f"{base}.description",
            value=f"{kind} evidence {amount} {currency}",
        )
        _upsert_reviewed_extraction(db, run=run, document=document, field_path=f"{base}.amount", value=amount)
        _upsert_reviewed_extraction(db, run=run, document=document, field_path=f"{base}.category_candidate", value="Fixture")
        db.flush()
        sync_financial_review(db, claim=claim, user_id=user.id)
        item = db.scalar(
            select(CostItem).where(
                CostItem.organization_id == claim.organization_id,
                CostItem.claim_id == claim.id,
                CostItem.ai_run_id == run.id,
                CostItem.source_field_prefix == base,
            )
        )
        assert item is not None
        item.review_status = status
        db.commit()
        return item.id


def _add_flag(claim_id: str, *, severity: str = "high") -> UUID:
    assert severity == "high", "This fixture intentionally exercises the deterministic high duplicate-invoice flag."
    _add_cost(
        claim_id,
        amount="1250",
        currency="USD",
        status=CostReviewStatus.UNDER_REVIEW,
        supplier="Duplicate Supplier",
        document_number="DUP-INV-1",
    )
    _add_cost(
        claim_id,
        amount="1250",
        currency="USD",
        status=CostReviewStatus.UNDER_REVIEW,
        supplier="Duplicate Supplier",
        document_number="DUP-INV-1",
    )
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        user = db.scalar(select(User).where(User.organization_id == claim.organization_id))
        sync_financial_review(db, claim=claim, user_id=user.id)
        flag = db.scalar(
            select(FinancialFlag).where(
                FinancialFlag.organization_id == claim.organization_id,
                FinancialFlag.claim_id == claim.id,
                FinancialFlag.flag_type == "possible_duplicate",
                FinancialFlag.status == "open",
            )
        )
        assert flag is not None
        db.commit()
        return flag.id


def _reserve_count(claim_id: str) -> int:
    with TestingSessionLocal() as db:
        return db.scalar(
            select(func.count()).select_from(ReserveHistory).where(ReserveHistory.claim_id == UUID(claim_id))
        ) or 0


def test_no_monetary_evidence_never_invents_reserve_range_and_reuses_snapshot() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)

    before = _reserve_count(claim_id)
    first = _build(claim_id)
    second = _build(claim_id)
    after = _reserve_count(claim_id)

    assert first["id"] == second["id"]
    assert first["snapshot_version"] == 1
    assert first["engine_version"] == "12D.1"
    assert len(first["source_state_hash"]) == 64
    assert len(first["snapshot_hash"]) == 64
    assert first["summary"]["reserve_history_updated"] is False
    assert first["summary"]["financial_review_state_mutated"] is False
    assert first["summary"]["financial_evidence_refreshed"] is True
    assert first["summary"]["human_cost_review_decision_mutated"] is False
    assert before == after == 0

    reserve = next(row for row in first["evaluations"] if row["kind"] == "reserve")
    assert reserve["status"] == "insufficient_evidence"
    assert reserve["lower_amount"] is None
    assert reserve["upper_amount"] is None
    assert "reviewed monetary evidence" in reserve["missing_prerequisites"][0]


def test_reserve_range_uses_reviewed_target_currency_evidence_without_fx_or_rejected_costs() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)

    _add_cost(claim_id, amount="100000", currency="USD", status=CostReviewStatus.PAID, line_index=0)
    _add_cost(claim_id, amount="250000", currency="USD", status=CostReviewStatus.UNDER_REVIEW, line_index=1)
    _add_cost(claim_id, amount="900000", currency="USD", status=CostReviewStatus.REJECTED, line_index=2)
    _add_cost(claim_id, amount="50000", currency="EUR", status=CostReviewStatus.UNDER_REVIEW, line_index=3)
    quote_document = uuid4()
    _add_cost(
        claim_id,
        amount="400000",
        currency="USD",
        status=CostReviewStatus.UNDER_REVIEW,
        kind="quotation",
        document_id=quote_document,
        line_index=0,
        supplier="Repair Yard A",
    )
    _add_cost(
        claim_id,
        amount="200000",
        currency="USD",
        status=CostReviewStatus.UNDER_REVIEW,
        kind="quotation",
        document_id=quote_document,
        line_index=1,
        supplier="Repair Yard A",
    )
    _add_fact(claim_id, "financial.estimated_repair_cost", 550000)
    _add_fact(claim_id, "financial.estimated_repair_cost_currency", "USD")

    snapshot = _build(claim_id)
    reserve = next(row for row in snapshot["evaluations"] if row["kind"] == "reserve")

    assert reserve["status"] == "triggered"
    assert reserve["currency"] == "USD"
    assert Decimal(str(reserve["lower_amount"])) == Decimal("100000.00")
    assert Decimal(str(reserve["upper_amount"])) == Decimal("600000.00")
    assert any(
        factor["factor"] == "non_rejected_invoice_exposure" and Decimal(factor["amount"]) == Decimal("350000")
        for factor in reserve["factors"]
    )
    assert any(
        factor["factor"] == "highest_reviewed_quotation" and Decimal(factor["amount"]) == Decimal("600000")
        for factor in reserve["factors"]
    )
    assert any("EUR" in item for item in reserve["missing_prerequisites"])
    assert not any(
        source.get("amount") == "900000.00" and source.get("review_status") != "rejected"
        for source in reserve["source_refs"]
    )
    assert _reserve_count(claim_id) == 0


def test_critical_timebar_and_high_financial_flag_raise_explainable_handling_severity() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_flag(claim_id, severity="high")
    _add_fact(claim_id, "recovery.counterparty", "Potential workshop")
    _add_fact(claim_id, "recovery.basis", "Reviewed workmanship investigation basis")
    _add_fact(claim_id, "timebar.source_reference", "Reviewed workshop notice clause")
    _add_fact(claim_id, "timebar.trigger_date", "2026-08-01")
    _add_fact(claim_id, "timebar.period_value", 45)
    _add_fact(claim_id, "timebar.period_unit", "days")

    snapshot = _build(claim_id)
    severity = next(row for row in snapshot["evaluations"] if row["kind"] == "severity")

    assert severity["status"] == "triggered"
    assert severity["severity_score"] >= 6
    assert severity["severity_label"] in {"high", "critical"}
    assert any(factor["factor"] == "open_high_financial_flag" for factor in severity["factors"])
    assert any(
        factor["factor"] == "recovery_timebar_urgency" and factor["urgency"] == "critical"
        for factor in severity["factors"]
    )
    assert any(source["kind"] == "financial_flag" for source in severity["source_refs"])
    assert any(source["kind"] == "recovery_timebar_evaluation" for source in severity["source_refs"])


def test_human_decisions_are_hash_chained_stale_safe_and_never_change_reserve_history() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "financial.estimated_repair_cost", 500000)
    _add_fact(claim_id, "financial.estimated_repair_cost_currency", "USD")

    first = _build(claim_id)
    reserve = next(row for row in first["evaluations"] if row["kind"] == "reserve")

    edited = client.post(
        f"/api/v1/claims/{claim_id}/severity-reserve/evaluations/{reserve['id']}/decision",
        json={
            "action": "edit",
            "evaluation_hash": reserve["evaluation_hash"],
            "note": "Human review narrows the working range without changing the authoritative reserve.",
            "edited_lower_amount": "100000",
            "edited_upper_amount": "450000",
        },
    )
    assert edited.status_code == 200, edited.text
    first_decision = edited.json()
    assert first_decision["decision_number"] == 1
    assert len(first_decision["decision_hash"]) == 64
    assert _reserve_count(claim_id) == 0

    accepted = client.post(
        f"/api/v1/claims/{claim_id}/severity-reserve/evaluations/{reserve['id']}/decision",
        json={
            "action": "accept",
            "evaluation_hash": reserve["evaluation_hash"],
            "note": "Human reviewer accepts the support output as a review aid only.",
        },
    )
    assert accepted.status_code == 200, accepted.text
    second_decision = accepted.json()
    assert second_decision["decision_number"] == 2
    assert second_decision["previous_decision_hash"] == first_decision["decision_hash"]
    assert _reserve_count(claim_id) == 0

    _add_cost(claim_id, amount="125000", currency="USD", status=CostReviewStatus.PAID)
    second = _build(claim_id)
    assert second["snapshot_version"] == 2
    assert second["id"] != first["id"]

    stale = client.post(
        f"/api/v1/claims/{claim_id}/severity-reserve/evaluations/{reserve['id']}/decision",
        json={
            "action": "dismiss",
            "evaluation_hash": reserve["evaluation_hash"],
            "note": "Attempted disposition on a superseded immutable support evaluation.",
        },
    )
    assert stale.status_code == 409

    with TestingSessionLocal() as db:
        decisions = list(
            db.scalars(
                select(SeverityReserveDecision)
                .where(SeverityReserveDecision.evaluation_id == UUID(reserve["id"]))
                .order_by(SeverityReserveDecision.decision_number.asc())
            )
        )
        assert [row.decision_number for row in decisions] == [1, 2]
        snapshots = list(
            db.scalars(
                select(SeverityReserveSnapshot)
                .where(SeverityReserveSnapshot.claim_id == UUID(claim_id))
                .order_by(SeverityReserveSnapshot.snapshot_version.asc())
            )
        )
        assert [row.snapshot_version for row in snapshots] == [1, 2]
        assert db.scalar(
            select(func.count()).select_from(ReserveHistory).where(ReserveHistory.claim_id == UUID(claim_id))
        ) == 0

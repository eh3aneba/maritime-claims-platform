from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.adjustments.models import (
    AdjustmentBasis,
    AdjustmentLine,
    AdjustmentStatement,
    AdjustmentStatus,
    AdjustmentTreatment,
)
from app.modules.adjustments.schemas import AdjustmentCreate, AdjustmentLineUpdate, AdjustmentStatementUpdate
from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.financial.models import CostItem
from app.modules.users.models import User


_ZERO = Decimal("0.00")


def _lines(db: Session, statement: AdjustmentStatement) -> list[AdjustmentLine]:
    return list(db.scalars(select(AdjustmentLine).where(
        AdjustmentLine.statement_id == statement.id,
        AdjustmentLine.organization_id == statement.organization_id,
        AdjustmentLine.claim_id == statement.claim_id,
    ).order_by(AdjustmentLine.sort_order.asc())))


def _audit(db: Session, *, statement: AdjustmentStatement, user: User, action: str, values: dict, details: str | None = None) -> None:
    write_audit_log(
        db,
        organization_id=statement.organization_id,
        user_id=user.id,
        action=action,
        entity_type="adjustment_statement",
        entity_id=statement.id,
        new_values=values,
        details=details,
    )


def _recalculate(db: Session, statement: AdjustmentStatement) -> list[AdjustmentLine]:
    lines = _lines(db, statement)
    statement.gross_claimed = sum((line.claimed_amount for line in lines), _ZERO)
    statement.gross_considered = sum((line.considered_amount for line in lines), _ZERO)
    statement.net_adjusted = statement.gross_considered - statement.deductible_amount - statement.other_deduction_amount
    return lines


def _content_payload(statement: AdjustmentStatement, lines: list[AdjustmentLine]) -> dict:
    return {
        "version": statement.version,
        "title": statement.title,
        "currency": statement.currency,
        "deductible_amount": str(statement.deductible_amount),
        "deductible_basis": statement.deductible_basis,
        "other_deduction_amount": str(statement.other_deduction_amount),
        "other_deduction_basis": statement.other_deduction_basis,
        "gross_claimed": str(statement.gross_claimed),
        "gross_considered": str(statement.gross_considered),
        "net_adjusted": str(statement.net_adjusted),
        "source_manifest": statement.source_manifest,
        "lines": [
            {
                "id": str(line.id),
                "cost_item_id": str(line.cost_item_id) if line.cost_item_id else None,
                "source_document_id": str(line.source_document_id) if line.source_document_id else None,
                "sort_order": line.sort_order,
                "description": line.description,
                "supplier": line.supplier,
                "document_number": line.document_number,
                "category": line.category,
                "claimed_amount": str(line.claimed_amount),
                "considered_amount": str(line.considered_amount),
                "treatment": line.treatment.value,
                "basis": line.basis.value,
                "reason": line.reason,
                "note": line.note,
                "source_snapshot": line.source_snapshot,
            }
            for line in lines
        ],
    }


def _hash(statement: AdjustmentStatement, lines: list[AdjustmentLine]) -> str:
    encoded = json.dumps(_content_payload(statement, lines), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def statement_response(db: Session, statement: AdjustmentStatement) -> dict:
    lines = _lines(db, statement)
    return {
        "id": statement.id,
        "claim_id": statement.claim_id,
        "created_by_id": statement.created_by_id,
        "reviewed_by_id": statement.reviewed_by_id,
        "version": statement.version,
        "title": statement.title,
        "currency": statement.currency,
        "status": statement.status,
        "deductible_amount": statement.deductible_amount,
        "deductible_basis": statement.deductible_basis,
        "other_deduction_amount": statement.other_deduction_amount,
        "other_deduction_basis": statement.other_deduction_basis,
        "gross_claimed": statement.gross_claimed,
        "gross_considered": statement.gross_considered,
        "net_adjusted": statement.net_adjusted,
        "source_manifest": statement.source_manifest,
        "review_note": statement.review_note,
        "content_hash": statement.content_hash,
        "reviewed_at": statement.reviewed_at,
        "created_at": statement.created_at,
        "updated_at": statement.updated_at,
        "lines": lines,
    }


def list_statements(db: Session, *, claim: Claim) -> list[AdjustmentStatement]:
    return list(db.scalars(select(AdjustmentStatement).where(
        AdjustmentStatement.organization_id == claim.organization_id,
        AdjustmentStatement.claim_id == claim.id,
    ).order_by(AdjustmentStatement.version.desc())))


def get_statement(db: Session, *, claim: Claim, statement_id: UUID) -> AdjustmentStatement:
    statement = db.scalar(select(AdjustmentStatement).where(
        AdjustmentStatement.id == statement_id,
        AdjustmentStatement.organization_id == claim.organization_id,
        AdjustmentStatement.claim_id == claim.id,
    ))
    if statement is None:
        raise HTTPException(status_code=404, detail="Adjustment statement not found")
    return statement


def create_statement(db: Session, *, claim: Claim, user: User, payload: AdjustmentCreate) -> AdjustmentStatement:
    currency = payload.currency.strip().upper()
    items = list(db.scalars(select(CostItem).where(
        CostItem.organization_id == claim.organization_id,
        CostItem.claim_id == claim.id,
        CostItem.document_kind == "invoice",
        CostItem.currency == currency,
    ).order_by(CostItem.created_at.asc(), CostItem.line_index.asc())))
    if not items:
        raise HTTPException(status_code=409, detail=f"No human-reviewed invoice cost items are available in {currency}")

    current_version = db.scalar(select(func.max(AdjustmentStatement.version)).where(AdjustmentStatement.claim_id == claim.id)) or 0
    statement = AdjustmentStatement(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        created_by_id=user.id,
        version=current_version + 1,
        title=(payload.title or f"{claim.claim_reference} – Adjustment Statement").strip(),
        currency=currency,
        status=AdjustmentStatus.DRAFT,
        deductible_amount=_ZERO,
        other_deduction_amount=_ZERO,
        gross_claimed=_ZERO,
        gross_considered=_ZERO,
        net_adjusted=_ZERO,
        source_manifest=[
            {
                "cost_item_id": str(item.id),
                "document_id": str(item.document_id),
                "ai_run_id": str(item.ai_run_id),
                "document_kind": item.document_kind,
                "currency": item.currency,
                "review_status": item.review_status.value,
            }
            for item in items
        ],
    )
    db.add(statement)
    db.flush()

    for index, item in enumerate(items, 1):
        db.add(AdjustmentLine(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            statement_id=statement.id,
            cost_item_id=item.id,
            source_document_id=item.document_id,
            sort_order=index,
            description=item.description,
            supplier=item.supplier,
            document_number=item.document_number,
            category=item.category,
            claimed_amount=item.amount,
            considered_amount=_ZERO,
            treatment=AdjustmentTreatment.PENDING,
            basis=AdjustmentBasis.UNALLOCATED,
            source_snapshot={
                "cost_item_id": str(item.id),
                "document_id": str(item.document_id),
                "ai_run_id": str(item.ai_run_id),
                "line_index": item.line_index,
                "description": item.description,
                "amount": str(item.amount),
                "currency": item.currency,
                "review_status": item.review_status.value,
            },
        ))
    db.flush()
    _recalculate(db, statement)
    _audit(db, statement=statement, user=user, action="CREATE_ADJUSTMENT_STATEMENT", values={"version": statement.version, "currency": currency, "line_count": len(items)})
    db.commit()
    db.refresh(statement)
    return statement


def _ensure_editable(statement: AdjustmentStatement) -> None:
    if statement.status not in {AdjustmentStatus.DRAFT, AdjustmentStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="Only draft or rejected adjustment statements can be edited")


def update_statement(db: Session, *, statement: AdjustmentStatement, user: User, payload: AdjustmentStatementUpdate) -> AdjustmentStatement:
    _ensure_editable(statement)
    if payload.title is not None:
        statement.title = payload.title.strip()
    if payload.deductible_amount is not None:
        statement.deductible_amount = payload.deductible_amount
    if payload.deductible_basis is not None:
        statement.deductible_basis = payload.deductible_basis.strip() or None
    if payload.other_deduction_amount is not None:
        statement.other_deduction_amount = payload.other_deduction_amount
    if payload.other_deduction_basis is not None:
        statement.other_deduction_basis = payload.other_deduction_basis.strip() or None
    statement.status = AdjustmentStatus.DRAFT
    statement.review_note = None
    statement.reviewed_by_id = None
    statement.reviewed_at = None
    statement.content_hash = None
    _recalculate(db, statement)
    _audit(db, statement=statement, user=user, action="UPDATE_ADJUSTMENT_STATEMENT", values={"deductible_amount": str(statement.deductible_amount), "other_deduction_amount": str(statement.other_deduction_amount)})
    db.commit()
    db.refresh(statement)
    return statement


def update_line(db: Session, *, statement: AdjustmentStatement, line_id: UUID, user: User, payload: AdjustmentLineUpdate) -> AdjustmentStatement:
    _ensure_editable(statement)
    line = db.scalar(select(AdjustmentLine).where(
        AdjustmentLine.id == line_id,
        AdjustmentLine.statement_id == statement.id,
        AdjustmentLine.organization_id == statement.organization_id,
        AdjustmentLine.claim_id == statement.claim_id,
    ))
    if line is None:
        raise HTTPException(status_code=404, detail="Adjustment line not found")
    amount = payload.considered_amount
    if payload.treatment in {AdjustmentTreatment.INCLUDED, AdjustmentTreatment.APPORTIONED} and (amount < 0 or amount > line.claimed_amount):
        raise HTTPException(status_code=422, detail="Included/apportioned amount must be between zero and the claimed amount")
    if payload.treatment == AdjustmentTreatment.EXCLUDED and amount != 0:
        raise HTTPException(status_code=422, detail="Excluded lines must have a zero considered amount")
    if payload.treatment == AdjustmentTreatment.CREDIT and amount > 0:
        raise HTTPException(status_code=422, detail="Credit lines must use a zero or negative considered amount")
    line.treatment = payload.treatment
    line.basis = payload.basis
    line.considered_amount = amount
    line.reason = (payload.reason or "").strip() or None
    line.note = (payload.note or "").strip() or None
    statement.status = AdjustmentStatus.DRAFT
    statement.review_note = None
    statement.reviewed_by_id = None
    statement.reviewed_at = None
    statement.content_hash = None
    _recalculate(db, statement)
    _audit(db, statement=statement, user=user, action="UPDATE_ADJUSTMENT_LINE", values={"line_id": str(line.id), "treatment": line.treatment.value, "basis": line.basis.value, "considered_amount": str(line.considered_amount)})
    db.commit()
    db.refresh(statement)
    return statement


def _validate_submission(statement: AdjustmentStatement, lines: list[AdjustmentLine]) -> None:
    errors: list[str] = []
    for line in lines:
        label = f"Line {line.sort_order}"
        if line.treatment == AdjustmentTreatment.PENDING:
            errors.append(f"{label}: treatment is pending")
        if line.basis == AdjustmentBasis.UNALLOCATED:
            errors.append(f"{label}: adjustment basis is unallocated")
        if line.treatment == AdjustmentTreatment.EXCLUDED and line.considered_amount != 0:
            errors.append(f"{label}: excluded amount must be zero")
        if line.treatment == AdjustmentTreatment.CREDIT and line.considered_amount > 0:
            errors.append(f"{label}: credit amount must be zero or negative")
        if line.treatment in {AdjustmentTreatment.INCLUDED, AdjustmentTreatment.APPORTIONED} and (line.considered_amount < 0 or line.considered_amount > line.claimed_amount):
            errors.append(f"{label}: considered amount is outside the claimed amount")
        if (line.treatment in {AdjustmentTreatment.EXCLUDED, AdjustmentTreatment.APPORTIONED, AdjustmentTreatment.CREDIT} or line.considered_amount != line.claimed_amount) and not (line.reason or "").strip():
            errors.append(f"{label}: adjustment reason is required")
    if statement.deductible_amount > 0 and not (statement.deductible_basis or "").strip():
        errors.append("Deductible basis is required")
    if statement.other_deduction_amount > 0 and not (statement.other_deduction_basis or "").strip():
        errors.append("Other deduction/credit basis is required")
    if statement.gross_considered < 0:
        errors.append("Gross considered amount cannot be negative")
    if statement.deductible_amount + statement.other_deduction_amount > statement.gross_considered:
        errors.append("Statement deductions cannot exceed the gross considered amount")
    if errors:
        raise HTTPException(status_code=409, detail="; ".join(errors))


def submit_statement(db: Session, *, statement: AdjustmentStatement, user: User) -> AdjustmentStatement:
    if statement.status not in {AdjustmentStatus.DRAFT, AdjustmentStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="Only draft or rejected statements can be submitted")
    lines = _recalculate(db, statement)
    _validate_submission(statement, lines)
    statement.status = AdjustmentStatus.UNDER_REVIEW
    _audit(db, statement=statement, user=user, action="SUBMIT_ADJUSTMENT_FOR_REVIEW", values={"status": statement.status.value, "net_adjusted": str(statement.net_adjusted)})
    db.commit()
    db.refresh(statement)
    return statement


def review_statement(db: Session, *, statement: AdjustmentStatement, user: User, approve: bool, note: str) -> AdjustmentStatement:
    if statement.status != AdjustmentStatus.UNDER_REVIEW:
        raise HTTPException(status_code=409, detail="Only statements under review can be approved or rejected")
    lines = _recalculate(db, statement)
    _validate_submission(statement, lines)
    statement.status = AdjustmentStatus.APPROVED if approve else AdjustmentStatus.REJECTED
    statement.review_note = note.strip()
    statement.reviewed_by_id = user.id
    statement.reviewed_at = datetime.now(UTC)
    statement.content_hash = _hash(statement, lines) if approve else None
    _audit(db, statement=statement, user=user, action="APPROVE_ADJUSTMENT_STATEMENT" if approve else "REJECT_ADJUSTMENT_STATEMENT", values={"status": statement.status.value, "content_hash": statement.content_hash, "net_adjusted": str(statement.net_adjusted)}, details="Approved adjustment is a human-reviewed calculation record, not payment authorization or an automated coverage decision." if approve else None)
    db.commit()
    db.refresh(statement)
    return statement

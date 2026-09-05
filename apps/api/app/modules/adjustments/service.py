from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from typing import Any
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
from app.modules.adjustments.schemas import (
    AdjustmentCreate,
    AdjustmentLineUpdate,
    AdjustmentRebase,
    AdjustmentStatementUpdate,
)
from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.financial.service import build_financial_review
from app.modules.users.models import User


_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")
_SOURCE_MANIFEST_VERSION = 2


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def _lines(db: Session, statement: AdjustmentStatement) -> list[AdjustmentLine]:
    return list(
        db.scalars(
            select(AdjustmentLine)
            .where(
                AdjustmentLine.statement_id == statement.id,
                AdjustmentLine.organization_id == statement.organization_id,
                AdjustmentLine.claim_id == statement.claim_id,
            )
            .order_by(AdjustmentLine.sort_order.asc())
        )
    )


def _audit(
    db: Session,
    *,
    statement: AdjustmentStatement,
    user: User,
    action: str,
    values: dict,
    details: str | None = None,
) -> None:
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


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(encoded).hexdigest()


def _manifest_row(item: dict[str, Any], target_currency: str) -> dict[str, Any]:
    latest = item.get("latest_review_decision") or {}
    review_status = item["review_status"]
    if hasattr(review_status, "value"):
        review_status = review_status.value
    return {
        "item_key": item["item_key"],
        "cost_item_id": str(item["id"]),
        "document_id": str(item["document_id"]),
        "document_family_id": str(item["document_family_id"]),
        "document_version": item["document_version"],
        "document_kind": item["document_kind"],
        "source_state": item["source_state"],
        "state_fingerprint": item["state_fingerprint"],
        "state_version": item["state_version"],
        "decision_state": item["decision_state"],
        "latest_review_decision_hash": latest.get("decision_hash"),
        "review_status": review_status,
        "description": item["description"],
        "supplier": item.get("supplier"),
        "document_number": item.get("document_number"),
        "category": item.get("category"),
        "source_amount": str(_money(Decimal(item["amount"]))),
        "source_currency": item["currency"].upper(),
        "target_currency": target_currency,
        "line_index": item["line_index"],
    }


def _financial_source_bundle(
    db: Session,
    *,
    claim: Claim,
    currency: str,
    user_id: UUID | None,
) -> tuple[list[dict[str, Any]], str]:
    review = build_financial_review(db, claim=claim, user_id=user_id)
    manifest = [
        _manifest_row(item, currency)
        for item in review["items"]
        if item["document_kind"] == "invoice"
    ]
    manifest.sort(key=lambda row: row["item_key"])
    source_hash = _hash_payload(
        {
            "schema_version": _SOURCE_MANIFEST_VERSION,
            "claim_id": str(claim.id),
            "target_currency": currency,
            "invoice_items": manifest,
        }
    )
    return manifest, source_hash


def _source_change_summary(stored: list[dict], current: list[dict]) -> dict[str, Any]:
    stored_by_key = {row.get("item_key"): row for row in stored if row.get("item_key")}
    current_by_key = {row.get("item_key"): row for row in current if row.get("item_key")}
    added = sorted(key for key in current_by_key if key not in stored_by_key)
    removed = sorted(key for key in stored_by_key if key not in current_by_key)
    changed: list[str] = []
    for key in sorted(set(stored_by_key) & set(current_by_key)):
        old = stored_by_key[key]
        new = current_by_key[key]
        identity_fields = (
            "state_fingerprint",
            "state_version",
            "decision_state",
            "latest_review_decision_hash",
            "review_status",
            "document_id",
            "document_version",
            "source_amount",
            "source_currency",
        )
        if any(old.get(field) != new.get(field) for field in identity_fields):
            changed.append(key)
    return {
        "added_item_keys": added,
        "removed_item_keys": removed,
        "changed_item_keys": changed,
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
    }


def adjustment_source_state(
    db: Session,
    *,
    statement: AdjustmentStatement,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    claim = db.scalar(
        select(Claim).where(
            Claim.id == statement.claim_id,
            Claim.organization_id == statement.organization_id,
        )
    )
    if claim is None:
        return {
            "status": "source_unavailable",
            "current_hash": None,
            "current_manifest": [],
            "change_summary": {
                "added_item_keys": [],
                "removed_item_keys": [],
                "changed_item_keys": [],
                "added_count": 0,
                "removed_count": 0,
                "changed_count": 0,
            },
        }
    current_manifest, current_hash = _financial_source_bundle(
        db,
        claim=claim,
        currency=statement.currency,
        user_id=user_id,
    )
    if statement.source_state_hash is None:
        status = "legacy_unbound"
    elif statement.source_state_hash == current_hash:
        status = "current"
    else:
        status = "stale"
    return {
        "status": status,
        "current_hash": current_hash,
        "current_manifest": current_manifest,
        "change_summary": _source_change_summary(statement.source_manifest or [], current_manifest),
    }


def _ensure_current_source(db: Session, *, statement: AdjustmentStatement, user_id: UUID | None) -> None:
    source = adjustment_source_state(db, statement=statement, user_id=user_id)
    if source["status"] != "current":
        raise HTTPException(
            status_code=409,
            detail=(
                "Adjustment source evidence has changed or predates state-bound source tracking. "
                "Create an explicit rebased version before editing, submitting or approving it."
            ),
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
        "rebased_from_statement_id": str(statement.rebased_from_statement_id) if statement.rebased_from_statement_id else None,
        "title": statement.title,
        "currency": statement.currency,
        "deductible_amount": str(statement.deductible_amount),
        "deductible_basis": statement.deductible_basis,
        "other_deduction_amount": str(statement.other_deduction_amount),
        "other_deduction_basis": statement.other_deduction_basis,
        "gross_claimed": str(statement.gross_claimed),
        "gross_considered": str(statement.gross_considered),
        "net_adjusted": str(statement.net_adjusted),
        "source_manifest_version": statement.source_manifest_version,
        "source_state_hash": statement.source_state_hash,
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
                "financial_controls": line.financial_controls,
            }
            for line in lines
        ],
    }


def _hash(statement: AdjustmentStatement, lines: list[AdjustmentLine]) -> str:
    return _hash_payload(_content_payload(statement, lines))


def statement_response(db: Session, statement: AdjustmentStatement) -> dict:
    lines = _lines(db, statement)
    source = adjustment_source_state(db, statement=statement)
    return {
        "id": statement.id,
        "claim_id": statement.claim_id,
        "created_by_id": statement.created_by_id,
        "reviewed_by_id": statement.reviewed_by_id,
        "rebased_from_statement_id": statement.rebased_from_statement_id,
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
        "source_manifest_version": statement.source_manifest_version,
        "source_state_hash": statement.source_state_hash,
        "current_source_state_hash": source["current_hash"],
        "source_state_status": source["status"],
        "source_change_summary": source["change_summary"],
        "review_note": statement.review_note,
        "content_hash": statement.content_hash,
        "reviewed_at": statement.reviewed_at,
        "created_at": statement.created_at,
        "updated_at": statement.updated_at,
        "lines": lines,
    }


def list_statements(db: Session, *, claim: Claim) -> list[AdjustmentStatement]:
    return list(
        db.scalars(
            select(AdjustmentStatement)
            .where(
                AdjustmentStatement.organization_id == claim.organization_id,
                AdjustmentStatement.claim_id == claim.id,
            )
            .order_by(AdjustmentStatement.version.desc())
        )
    )


def get_statement(db: Session, *, claim: Claim, statement_id: UUID) -> AdjustmentStatement:
    statement = db.scalar(
        select(AdjustmentStatement).where(
            AdjustmentStatement.id == statement_id,
            AdjustmentStatement.organization_id == claim.organization_id,
            AdjustmentStatement.claim_id == claim.id,
        )
    )
    if statement is None:
        raise HTTPException(status_code=404, detail="Adjustment statement not found")
    return statement


def _new_line_from_manifest(
    *,
    claim: Claim,
    statement: AdjustmentStatement,
    manifest_row: dict[str, Any],
    sort_order: int,
) -> AdjustmentLine:
    source_amount = Decimal(manifest_row["source_amount"])
    same_currency = manifest_row["source_currency"] == statement.currency
    return AdjustmentLine(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        statement_id=statement.id,
        cost_item_id=UUID(manifest_row["cost_item_id"]),
        source_document_id=UUID(manifest_row["document_id"]),
        sort_order=sort_order,
        description=manifest_row["description"],
        supplier=manifest_row.get("supplier"),
        document_number=manifest_row.get("document_number"),
        category=manifest_row.get("category"),
        claimed_amount=source_amount if same_currency else _ZERO,
        considered_amount=_ZERO,
        treatment=AdjustmentTreatment.PENDING,
        basis=AdjustmentBasis.UNALLOCATED,
        source_snapshot=dict(manifest_row),
        financial_controls={},
    )


def create_statement(db: Session, *, claim: Claim, user: User, payload: AdjustmentCreate) -> AdjustmentStatement:
    currency = payload.currency.strip().upper()
    manifest, source_hash = _financial_source_bundle(db, claim=claim, currency=currency, user_id=user.id)
    if not manifest:
        raise HTTPException(status_code=409, detail="No current human-reviewed invoice cost items are available")

    current_version = db.scalar(
        select(func.max(AdjustmentStatement.version)).where(
            AdjustmentStatement.claim_id == claim.id,
            AdjustmentStatement.organization_id == claim.organization_id,
        )
    ) or 0
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
        source_manifest=manifest,
        source_manifest_version=_SOURCE_MANIFEST_VERSION,
        source_state_hash=source_hash,
    )
    db.add(statement)
    db.flush()
    for index, row in enumerate(manifest, 1):
        db.add(_new_line_from_manifest(claim=claim, statement=statement, manifest_row=row, sort_order=index))
    db.flush()
    _recalculate(db, statement)
    _audit(
        db,
        statement=statement,
        user=user,
        action="CREATE_ADJUSTMENT_STATEMENT",
        values={
            "version": statement.version,
            "currency": currency,
            "line_count": len(manifest),
            "source_state_hash": source_hash,
            "source_manifest_version": _SOURCE_MANIFEST_VERSION,
        },
        details="Created a draft from current usable financial evidence. No line treatment, FX rate, deduction or recoverability decision was inferred.",
    )
    db.commit()
    db.refresh(statement)
    return statement


def _ensure_editable(statement: AdjustmentStatement) -> None:
    if statement.status not in {AdjustmentStatus.DRAFT, AdjustmentStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="Only draft or rejected adjustment statements can be edited")


def _normalize_controls(
    *,
    payload_controls,
    claimed_amount: Decimal,
) -> dict[str, Any]:
    if payload_controls is None:
        return {}
    controls = payload_controls.model_dump(mode="json", exclude_none=True)
    for kind in ("tax", "depreciation", "betterment", "allocation"):
        control = controls.get(kind)
        if not control:
            continue
        percentage = control.get("percentage")
        amount = control.get("amount")
        if percentage is not None:
            computed = _money(claimed_amount * Decimal(str(percentage)) / Decimal("100"))
            control["computed_reference_amount"] = str(computed)
            if amount is not None and abs(_money(Decimal(str(amount))) - computed) > _CENT:
                raise HTTPException(
                    status_code=422,
                    detail=f"{kind.title()} amount does not match its stated percentage of the line claimed amount",
                )
    return controls


def _validate_source_amount_and_fx(
    *,
    statement: AdjustmentStatement,
    line: AdjustmentLine,
    claimed_amount: Decimal,
    controls: dict[str, Any],
) -> None:
    source_currency = str(line.source_snapshot.get("source_currency") or statement.currency).upper()
    source_amount = Decimal(str(line.source_snapshot.get("source_amount") or line.claimed_amount))
    target_currency = statement.currency.upper()
    fx = controls.get("fx")
    if source_currency == target_currency:
        if fx:
            raise HTTPException(status_code=422, detail="FX control is only valid for a cross-currency source line")
        if _money(claimed_amount) != _money(source_amount):
            raise HTTPException(status_code=422, detail="Same-currency claimed amount must match the source evidence amount")
        return
    if not fx:
        raise HTTPException(
            status_code=422,
            detail=f"FX rate, date and source are required to convert {source_currency} evidence into {target_currency}",
        )
    if str(fx.get("source_currency", "")).upper() != source_currency or str(fx.get("target_currency", "")).upper() != target_currency:
        raise HTTPException(status_code=422, detail="FX control currencies do not match the source and statement currencies")
    expected = _money(source_amount * Decimal(str(fx["rate"])))
    if abs(_money(claimed_amount) - expected) > _CENT:
        raise HTTPException(
            status_code=422,
            detail=f"Claimed amount must equal source amount multiplied by the human-entered FX rate ({expected})",
        )


def update_statement(
    db: Session,
    *,
    statement: AdjustmentStatement,
    user: User,
    payload: AdjustmentStatementUpdate,
) -> AdjustmentStatement:
    _ensure_editable(statement)
    _ensure_current_source(db, statement=statement, user_id=user.id)
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
    _audit(
        db,
        statement=statement,
        user=user,
        action="UPDATE_ADJUSTMENT_STATEMENT",
        values={
            "deductible_amount": str(statement.deductible_amount),
            "other_deduction_amount": str(statement.other_deduction_amount),
            "source_state_hash": statement.source_state_hash,
        },
    )
    db.commit()
    db.refresh(statement)
    return statement


def update_line(
    db: Session,
    *,
    statement: AdjustmentStatement,
    line_id: UUID,
    user: User,
    payload: AdjustmentLineUpdate,
) -> AdjustmentStatement:
    _ensure_editable(statement)
    _ensure_current_source(db, statement=statement, user_id=user.id)
    line = db.scalar(
        select(AdjustmentLine).where(
            AdjustmentLine.id == line_id,
            AdjustmentLine.statement_id == statement.id,
            AdjustmentLine.organization_id == statement.organization_id,
            AdjustmentLine.claim_id == statement.claim_id,
        )
    )
    if line is None:
        raise HTTPException(status_code=404, detail="Adjustment line not found")

    claimed_amount = payload.claimed_amount if payload.claimed_amount is not None else line.claimed_amount
    controls = _normalize_controls(
        payload_controls=payload.financial_controls,
        claimed_amount=claimed_amount,
    ) if payload.financial_controls is not None else dict(line.financial_controls or {})
    _validate_source_amount_and_fx(
        statement=statement,
        line=line,
        claimed_amount=claimed_amount,
        controls=controls,
    )

    amount = payload.considered_amount
    if payload.treatment in {AdjustmentTreatment.INCLUDED, AdjustmentTreatment.APPORTIONED} and (
        amount < 0 or amount > claimed_amount
    ):
        raise HTTPException(status_code=422, detail="Included/apportioned amount must be between zero and the claimed amount")
    if payload.treatment == AdjustmentTreatment.EXCLUDED and amount != 0:
        raise HTTPException(status_code=422, detail="Excluded lines must have a zero considered amount")
    if payload.treatment == AdjustmentTreatment.CREDIT and amount > 0:
        raise HTTPException(status_code=422, detail="Credit lines must use a zero or negative considered amount")

    line.claimed_amount = claimed_amount
    line.financial_controls = controls
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
    _audit(
        db,
        statement=statement,
        user=user,
        action="UPDATE_ADJUSTMENT_LINE",
        values={
            "line_id": str(line.id),
            "treatment": line.treatment.value,
            "basis": line.basis.value,
            "claimed_amount": str(line.claimed_amount),
            "considered_amount": str(line.considered_amount),
            "structured_control_keys": sorted((line.financial_controls or {}).keys()),
        },
        details="Structured controls record human-entered source-grounded parameters; the platform does not infer their legal or coverage treatment.",
    )
    db.commit()
    db.refresh(statement)
    return statement


def _validate_submission(statement: AdjustmentStatement, lines: list[AdjustmentLine]) -> None:
    errors: list[str] = []
    for line in lines:
        label = f"Line {line.sort_order}"
        try:
            _validate_source_amount_and_fx(
                statement=statement,
                line=line,
                claimed_amount=line.claimed_amount,
                controls=line.financial_controls or {},
            )
        except HTTPException as exc:
            errors.append(f"{label}: {exc.detail}")
        if line.treatment == AdjustmentTreatment.PENDING:
            errors.append(f"{label}: treatment is pending")
        if line.basis == AdjustmentBasis.UNALLOCATED:
            errors.append(f"{label}: adjustment basis is unallocated")
        if line.treatment == AdjustmentTreatment.EXCLUDED and line.considered_amount != 0:
            errors.append(f"{label}: excluded amount must be zero")
        if line.treatment == AdjustmentTreatment.CREDIT and line.considered_amount > 0:
            errors.append(f"{label}: credit amount must be zero or negative")
        if line.treatment in {AdjustmentTreatment.INCLUDED, AdjustmentTreatment.APPORTIONED} and (
            line.considered_amount < 0 or line.considered_amount > line.claimed_amount
        ):
            errors.append(f"{label}: considered amount is outside the claimed amount")
        if (
            line.treatment in {AdjustmentTreatment.EXCLUDED, AdjustmentTreatment.APPORTIONED, AdjustmentTreatment.CREDIT}
            or line.considered_amount != line.claimed_amount
        ) and not (line.reason or "").strip():
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
    _ensure_current_source(db, statement=statement, user_id=user.id)
    lines = _recalculate(db, statement)
    _validate_submission(statement, lines)
    statement.status = AdjustmentStatus.UNDER_REVIEW
    _audit(
        db,
        statement=statement,
        user=user,
        action="SUBMIT_ADJUSTMENT_FOR_REVIEW",
        values={
            "status": statement.status.value,
            "net_adjusted": str(statement.net_adjusted),
            "source_state_hash": statement.source_state_hash,
        },
    )
    db.commit()
    db.refresh(statement)
    return statement


def review_statement(
    db: Session,
    *,
    statement: AdjustmentStatement,
    user: User,
    approve: bool,
    note: str,
) -> AdjustmentStatement:
    if statement.status != AdjustmentStatus.UNDER_REVIEW:
        raise HTTPException(status_code=409, detail="Only statements under review can be approved or rejected")
    if approve:
        _ensure_current_source(db, statement=statement, user_id=user.id)
    lines = _recalculate(db, statement)
    _validate_submission(statement, lines)
    statement.status = AdjustmentStatus.APPROVED if approve else AdjustmentStatus.REJECTED
    statement.review_note = note.strip()
    statement.reviewed_by_id = user.id
    statement.reviewed_at = datetime.now(UTC)
    statement.content_hash = _hash(statement, lines) if approve else None
    _audit(
        db,
        statement=statement,
        user=user,
        action="APPROVE_ADJUSTMENT_STATEMENT" if approve else "REJECT_ADJUSTMENT_STATEMENT",
        values={
            "status": statement.status.value,
            "content_hash": statement.content_hash,
            "net_adjusted": str(statement.net_adjusted),
            "source_state_hash": statement.source_state_hash,
        },
        details=(
            "Approved adjustment is a human-reviewed calculation record bound to a specific financial evidence state, not payment authorization or an automated coverage decision."
            if approve
            else None
        ),
    )
    db.commit()
    db.refresh(statement)
    return statement


def rebase_statement(
    db: Session,
    *,
    claim: Claim,
    statement: AdjustmentStatement,
    user: User,
    payload: AdjustmentRebase,
) -> AdjustmentStatement:
    prior_source = adjustment_source_state(db, statement=statement, user_id=user.id)
    if prior_source["status"] == "current":
        raise HTTPException(status_code=409, detail="Adjustment is already current; create a normal new version if a fresh draft is required")

    manifest, source_hash = _financial_source_bundle(
        db,
        claim=claim,
        currency=statement.currency,
        user_id=user.id,
    )
    if not manifest:
        raise HTTPException(status_code=409, detail="No current human-reviewed invoice cost items are available for rebase")
    current_version = db.scalar(
        select(func.max(AdjustmentStatement.version)).where(
            AdjustmentStatement.claim_id == claim.id,
            AdjustmentStatement.organization_id == claim.organization_id,
        )
    ) or 0
    rebased = AdjustmentStatement(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        created_by_id=user.id,
        rebased_from_statement_id=statement.id,
        version=current_version + 1,
        title=statement.title,
        currency=statement.currency,
        status=AdjustmentStatus.DRAFT,
        deductible_amount=statement.deductible_amount if payload.carry_statement_controls else _ZERO,
        deductible_basis=statement.deductible_basis if payload.carry_statement_controls else None,
        other_deduction_amount=statement.other_deduction_amount if payload.carry_statement_controls else _ZERO,
        other_deduction_basis=statement.other_deduction_basis if payload.carry_statement_controls else None,
        gross_claimed=_ZERO,
        gross_considered=_ZERO,
        net_adjusted=_ZERO,
        source_manifest=manifest,
        source_manifest_version=_SOURCE_MANIFEST_VERSION,
        source_state_hash=source_hash,
    )
    db.add(rebased)
    db.flush()

    prior_lines_by_key = {
        line.source_snapshot.get("item_key"): line
        for line in _lines(db, statement)
        if line.source_snapshot.get("item_key")
    }
    carried = 0
    reset = 0
    for index, row in enumerate(manifest, 1):
        new_line = _new_line_from_manifest(claim=claim, statement=rebased, manifest_row=row, sort_order=index)
        prior_line = prior_lines_by_key.get(row["item_key"])
        if prior_line is not None:
            old = prior_line.source_snapshot or {}
            unchanged = (
                old.get("state_fingerprint") == row.get("state_fingerprint")
                and old.get("latest_review_decision_hash") == row.get("latest_review_decision_hash")
                and old.get("source_amount") == row.get("source_amount")
                and old.get("source_currency") == row.get("source_currency")
            )
            if unchanged:
                new_line.claimed_amount = prior_line.claimed_amount
                new_line.considered_amount = prior_line.considered_amount
                new_line.treatment = prior_line.treatment
                new_line.basis = prior_line.basis
                new_line.reason = prior_line.reason
                new_line.note = prior_line.note
                new_line.financial_controls = dict(prior_line.financial_controls or {})
                carried += 1
            else:
                reset += 1
        else:
            reset += 1
        db.add(new_line)
    db.flush()
    _recalculate(db, rebased)
    _audit(
        db,
        statement=rebased,
        user=user,
        action="REBASE_ADJUSTMENT_STATEMENT",
        values={
            "rebased_from_statement_id": str(statement.id),
            "prior_source_status": prior_source["status"],
            "prior_source_state_hash": statement.source_state_hash,
            "new_source_state_hash": source_hash,
            "carried_line_count": carried,
            "reset_line_count": reset,
            "carry_statement_controls": payload.carry_statement_controls,
            "note": payload.note,
        },
        details=(
            "Explicit rebase created a new draft. Only line judgments whose exact evidence fingerprint and human cost-review lineage remained unchanged were carried; changed/new lines were reset for review."
        ),
    )
    db.commit()
    db.refresh(rebased)
    return rebased

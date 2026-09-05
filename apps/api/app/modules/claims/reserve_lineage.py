from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.adjustments.models import AdjustmentStatement, AdjustmentStatus
from app.modules.adjustments.service import adjustment_source_state
from app.modules.audit.service import write_audit_log
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.claims.schemas import ClaimReserveChange
from app.modules.financial.models import CostItem, CostReviewStatus, ReserveHistory
from app.modules.financial.service import sync_financial_review
from app.modules.severity_reserve.models import SeverityReserveEvaluation, SeverityReserveSnapshot
from app.modules.severity_reserve.service_core import _build_reserve_evaluation
from app.modules.users.models import User


class ReserveLineageError(ValueError):
    pass


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _hash(payload: Any) -> str:
    encoded = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _manual_source() -> tuple[str | None, dict[str, Any]]:
    return None, {
        "kind": "manual",
        "authority": "human_reserve_write",
        "upstream_financial_source_selected": False,
        "amount_inferred": False,
        "note": "Reserve amount was entered by the authorized human reviewer without selecting an upstream financial source.",
    }


def _quotation_summaries(items: list[CostItem]) -> list[dict[str, Any]]:
    groups: dict[tuple[UUID, str], dict[str, Any]] = {}
    for row in items:
        if row.document_kind != "quotation" or row.review_status == CostReviewStatus.REJECTED:
            continue
        currency = row.currency.upper()
        key = (row.document_id, currency)
        group = groups.setdefault(
            key,
            {
                "document_id": row.document_id,
                "supplier": row.supplier,
                "quotation_number": row.document_number,
                "currency": currency,
                "total": Decimal("0"),
            },
        )
        group["total"] += Decimal(row.amount)
        if not group.get("supplier") and row.supplier:
            group["supplier"] = row.supplier
        if not group.get("quotation_number") and row.document_number:
            group["quotation_number"] = row.document_number
    return list(groups.values())


def _reserve_support_source(
    db: Session,
    *,
    claim: Claim,
    user: User,
    snapshot_id: UUID,
) -> tuple[str, dict[str, Any]]:
    requested = db.scalar(
        select(SeverityReserveSnapshot).where(
            SeverityReserveSnapshot.id == snapshot_id,
            SeverityReserveSnapshot.organization_id == claim.organization_id,
            SeverityReserveSnapshot.claim_id == claim.id,
        )
    )
    if requested is None:
        raise ReserveLineageError("Reserve Support snapshot not found for this claim")

    latest = db.scalar(
        select(SeverityReserveSnapshot)
        .where(
            SeverityReserveSnapshot.organization_id == claim.organization_id,
            SeverityReserveSnapshot.claim_id == claim.id,
        )
        .order_by(SeverityReserveSnapshot.snapshot_version.desc())
        .limit(1)
    )
    if latest is None or latest.id != requested.id:
        raise ReserveLineageError(
            "Reserve Support source is superseded. Refresh support and deliberately review the latest snapshot before changing reserve."
        )

    reserve_eval = db.scalar(
        select(SeverityReserveEvaluation).where(
            SeverityReserveEvaluation.snapshot_id == requested.id,
            SeverityReserveEvaluation.organization_id == claim.organization_id,
            SeverityReserveEvaluation.claim_id == claim.id,
            SeverityReserveEvaluation.kind == "reserve",
        )
    )
    if reserve_eval is None:
        raise ReserveLineageError("Current Reserve Support snapshot has no reserve evaluation")
    if reserve_eval.currency and reserve_eval.currency.upper() != claim.currency.upper():
        raise ReserveLineageError("Reserve Support currency does not match the claim reserve currency")

    # Refresh only the derived current financial cache in this transaction. This
    # does not append human CostReviewDecision state and does not commit.
    sync_financial_review(db, claim=claim, user_id=user.id)
    cost_items = list(
        db.scalars(
            select(CostItem)
            .where(
                CostItem.organization_id == claim.organization_id,
                CostItem.claim_id == claim.id,
            )
            .order_by(CostItem.created_at.asc(), CostItem.id.asc())
        )
    )
    facts = list(
        db.scalars(
            select(ClaimFact).where(
                ClaimFact.organization_id == claim.organization_id,
                ClaimFact.claim_id == claim.id,
            )
        )
    )
    current_reserve = db.scalar(
        select(ReserveHistory)
        .where(
            ReserveHistory.organization_id == claim.organization_id,
            ReserveHistory.claim_id == claim.id,
        )
        .order_by(ReserveHistory.created_at.desc(), ReserveHistory.id.desc())
        .limit(1)
    )
    current_eval = _build_reserve_evaluation(
        claim=claim,
        cost_items=cost_items,
        quotations=_quotation_summaries(cost_items),
        facts=facts,
        current_reserve=current_reserve,
    )
    current_eval_hash = str(current_eval["evaluation_hash"])
    if current_eval_hash != reserve_eval.evaluation_hash:
        raise ReserveLineageError(
            "Reserve Support source is no longer current for reserve evaluation. Refresh support and deliberately review the new snapshot before changing reserve."
        )

    snapshot = {
        "kind": "reserve_support",
        "snapshot_id": str(requested.id),
        "snapshot_version": requested.snapshot_version,
        "snapshot_hash": requested.snapshot_hash,
        "support_source_state_hash": requested.source_state_hash,
        "evaluation_id": str(reserve_eval.id),
        "evaluation_hash": reserve_eval.evaluation_hash,
        "reserve_evaluation_current_verified": True,
        "status": reserve_eval.status,
        "currency": reserve_eval.currency,
        "lower_amount": str(reserve_eval.lower_amount) if reserve_eval.lower_amount is not None else None,
        "upper_amount": str(reserve_eval.upper_amount) if reserve_eval.upper_amount is not None else None,
        "advisory_only": True,
        "amount_inferred": False,
    }
    # For reserve provenance, the exact validated source identity is the reserve
    # evaluation hash; unrelated handling-severity changes do not authorize a
    # reserve write and are not treated as reserve amount authority.
    return current_eval_hash, snapshot


def _adjustment_source(
    db: Session,
    *,
    claim: Claim,
    statement_id: UUID,
    user_id: UUID,
) -> tuple[str, dict[str, Any]]:
    statement = db.scalar(
        select(AdjustmentStatement).where(
            AdjustmentStatement.id == statement_id,
            AdjustmentStatement.organization_id == claim.organization_id,
            AdjustmentStatement.claim_id == claim.id,
        )
    )
    if statement is None:
        raise ReserveLineageError("Adjustment statement not found for this claim")
    if statement.status != AdjustmentStatus.APPROVED:
        raise ReserveLineageError("Only an approved Adjustment can be recorded as reserve provenance")
    if statement.currency.upper() != claim.currency.upper():
        raise ReserveLineageError("Adjustment currency does not match the claim reserve currency")
    state = adjustment_source_state(db, statement=statement, user_id=user_id)
    if state["status"] != "current":
        raise ReserveLineageError(
            "Adjustment source is no longer current. Explicitly rebase and re-review it before using it as provenance for a new reserve change."
        )
    if not statement.content_hash:
        raise ReserveLineageError("Approved Adjustment is missing its immutable content hash")

    snapshot = {
        "kind": "adjustment",
        "statement_id": str(statement.id),
        "version": statement.version,
        "content_hash": statement.content_hash,
        "source_state_hash": statement.source_state_hash,
        "currency": statement.currency,
        "gross_claimed": str(statement.gross_claimed),
        "gross_considered": str(statement.gross_considered),
        "net_adjusted": str(statement.net_adjusted),
        "approved_by_id": str(statement.reviewed_by_id) if statement.reviewed_by_id else None,
        "approved_at": statement.reviewed_at.isoformat() if statement.reviewed_at else None,
        "amount_inferred": False,
    }
    return statement.source_state_hash or state["current_hash"], snapshot


def _source_bundle(
    db: Session,
    *,
    claim: Claim,
    user: User,
    payload: ClaimReserveChange,
) -> tuple[str | None, dict[str, Any]]:
    if payload.source_kind == "manual":
        return _manual_source()
    if payload.source_kind == "reserve_support":
        assert payload.source_reference_id is not None
        return _reserve_support_source(db, claim=claim, user=user, snapshot_id=payload.source_reference_id)
    assert payload.source_reference_id is not None
    return _adjustment_source(
        db,
        claim=claim,
        statement_id=payload.source_reference_id,
        user_id=user.id,
    )


def _request_payload(claim: Claim, payload: ClaimReserveChange) -> dict[str, Any]:
    """Stable human request identity; deliberately excludes later source state."""
    return {
        "claim_id": str(claim.id),
        "amount": str(payload.amount),
        "currency": claim.currency.upper(),
        "reason": payload.reason,
        "idempotency_key": payload.idempotency_key,
        "expected_reserve_version": payload.expected_reserve_version,
        "expected_reserve_hash": payload.expected_reserve_hash,
        "source_kind": payload.source_kind,
        "source_reference_id": str(payload.source_reference_id) if payload.source_reference_id else None,
    }


def reserve_history_response(db: Session, *, claim: Claim) -> dict[str, Any]:
    items = list(
        db.scalars(
            select(ReserveHistory)
            .where(
                ReserveHistory.organization_id == claim.organization_id,
                ReserveHistory.claim_id == claim.id,
            )
            .order_by(ReserveHistory.created_at.desc(), ReserveHistory.id.desc())
        )
    )
    current_lineage = next((row for row in items if row.sequence is not None), None)
    return {
        "claim_id": claim.id,
        "currency": claim.currency,
        "current_reserve": claim.current_reserve,
        "current_version": current_lineage.sequence if current_lineage else 0,
        "current_hash": current_lineage.reserve_hash if current_lineage else None,
        "items": items,
    }


def _existing_idempotency(
    db: Session,
    *,
    claim: Claim,
    payload: ClaimReserveChange,
    request_hash: str,
) -> ReserveHistory | None:
    existing = db.scalar(
        select(ReserveHistory).where(
            ReserveHistory.organization_id == claim.organization_id,
            ReserveHistory.claim_id == claim.id,
            ReserveHistory.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None and existing.request_hash != request_hash:
        raise ReserveLineageError("Idempotency key was already used with a different reserve request")
    return existing


def _current_lineage(db: Session, *, claim: Claim) -> tuple[ReserveHistory | None, int, str | None]:
    previous = db.scalar(
        select(ReserveHistory)
        .where(
            ReserveHistory.organization_id == claim.organization_id,
            ReserveHistory.claim_id == claim.id,
            ReserveHistory.sequence.is_not(None),
        )
        .order_by(ReserveHistory.sequence.desc())
        .limit(1)
    )
    current_version = previous.sequence if previous and previous.sequence is not None else 0
    current_hash = previous.reserve_hash if previous else None
    return previous, current_version, current_hash


def record_authoritative_reserve(
    db: Session,
    *,
    claim: Claim,
    user: User,
    payload: ClaimReserveChange,
) -> tuple[Claim, ReserveHistory, bool]:
    """Append one authoritative human reserve change.

    Upstream support/Adjustment is provenance only. The amount always comes from
    payload.amount and is never inferred, copied or selected by this service.
    """

    request_hash = _hash(_request_payload(claim, payload))

    # Exact retries remain replayable even if upstream evidence later evolves.
    existing = _existing_idempotency(db, claim=claim, payload=payload, request_hash=request_hash)
    if existing is not None:
        return claim, existing, True

    # Serialize authoritative reserve changes before checking the current lineage
    # token or validating provenance that includes current reserve context.
    locked_claim = db.scalar(
        select(Claim)
        .where(Claim.id == claim.id, Claim.organization_id == claim.organization_id)
        .with_for_update()
    )
    if locked_claim is None:
        raise ReserveLineageError("Claim not found")

    existing = _existing_idempotency(db, claim=locked_claim, payload=payload, request_hash=request_hash)
    if existing is not None:
        return locked_claim, existing, True

    previous, current_version, current_hash = _current_lineage(db, claim=locked_claim)
    if payload.expected_reserve_version != current_version or payload.expected_reserve_hash != current_hash:
        raise ReserveLineageError(
            "Authoritative reserve state changed. Reload reserve history and deliberately submit against the current version/hash."
        )

    # Validate optional provenance only after the authoritative reserve token is
    # known to be current. The validation path itself must not commit.
    source_state_hash, source_snapshot = _source_bundle(
        db,
        claim=locked_claim,
        user=user,
        payload=payload,
    )

    sequence = current_version + 1
    now = datetime.now(UTC)
    reserve_hash = _hash(
        {
            "previous_reserve_hash": current_hash,
            "sequence": sequence,
            "claim_id": str(locked_claim.id),
            "amount": str(payload.amount),
            "currency": locked_claim.currency.upper(),
            "reason": payload.reason,
            "source_kind": payload.source_kind,
            "source_reference_id": str(payload.source_reference_id) if payload.source_reference_id else None,
            "source_state_hash": source_state_hash,
            "source_snapshot": source_snapshot,
            "created_by_id": str(user.id),
            "created_at": now.isoformat(),
            "idempotency_key": payload.idempotency_key,
            "request_hash": request_hash,
        }
    )
    row = ReserveHistory(
        organization_id=locked_claim.organization_id,
        claim_id=locked_claim.id,
        amount=payload.amount,
        currency=locked_claim.currency.upper(),
        reason=payload.reason,
        created_by_id=user.id,
        created_at=now,
        sequence=sequence,
        idempotency_key=payload.idempotency_key,
        request_hash=request_hash,
        source_kind=payload.source_kind,
        source_reference_id=payload.source_reference_id,
        source_state_hash=source_state_hash,
        source_snapshot=source_snapshot,
        previous_reserve_hash=current_hash,
        reserve_hash=reserve_hash,
    )
    old_reserve = locked_claim.current_reserve
    locked_claim.current_reserve = payload.amount
    db.add(row)
    db.flush()
    write_audit_log(
        db,
        organization_id=locked_claim.organization_id,
        user_id=user.id,
        action="CHANGE_CLAIM_RESERVE",
        entity_type="claim",
        entity_id=locked_claim.id,
        old_values={
            "current_reserve": str(old_reserve) if old_reserve is not None else None,
            "reserve_version": current_version,
            "reserve_hash": current_hash,
        },
        new_values={
            "current_reserve": str(payload.amount),
            "reserve_version": sequence,
            "reserve_hash": reserve_hash,
            "source_kind": payload.source_kind,
            "source_reference_id": str(payload.source_reference_id) if payload.source_reference_id else None,
            "source_state_hash": source_state_hash,
            "amount_inferred": False,
        },
        details=payload.reason,
    )
    return locked_claim, row, False

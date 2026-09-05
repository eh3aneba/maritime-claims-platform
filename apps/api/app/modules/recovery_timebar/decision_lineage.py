from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.recovery_timebar import maturity as base
from app.modules.recovery_timebar.decision_models import RecoveryActionLog, RecoveryPursuitDecision
from app.modules.recovery_timebar.decision_schemas import (
    RecoveryActionLogWrite,
    RecoveryPursuitDecisionRevisionWrite,
    RecoveryPursuitDecisionWrite,
)
from app.modules.recovery_timebar.models import RecoveryCounterparty
from app.modules.recovery_timebar.service_core import _hash
from app.modules.users.models import User

DECISION_DISCLAIMER = (
    "Recovery dispositions and action logs are explicit human claim-handling records only. "
    "The platform does not determine liability, legal entitlement, recoverability, demand content, settlement or payment. "
    "A decision bound to superseded counterparty/source context is marked stale and cannot receive new actions until deliberately revised."
)


def _latest_decision(db: Session, *, claim: Claim, decision_key: UUID) -> RecoveryPursuitDecision | None:
    return db.scalar(
        select(RecoveryPursuitDecision)
        .where(
            RecoveryPursuitDecision.organization_id == claim.organization_id,
            RecoveryPursuitDecision.claim_id == claim.id,
            RecoveryPursuitDecision.decision_key == decision_key,
        )
        .order_by(RecoveryPursuitDecision.version.desc())
        .limit(1)
    )


def _counterparty_by_id(db: Session, *, claim: Claim, counterparty_id: UUID) -> RecoveryCounterparty | None:
    return db.scalar(
        select(RecoveryCounterparty).where(
            RecoveryCounterparty.id == counterparty_id,
            RecoveryCounterparty.organization_id == claim.organization_id,
            RecoveryCounterparty.claim_id == claim.id,
        )
    )


def _current_counterparty(db: Session, *, claim: Claim, counterparty_id: UUID) -> RecoveryCounterparty:
    row = _counterparty_by_id(db, claim=claim, counterparty_id=counterparty_id)
    if row is None:
        raise ValueError("Recovery counterparty does not belong to this claim")
    latest = base._latest_counterparty(db, claim=claim, counterparty_key=row.counterparty_key)
    if latest is None or latest.id != row.id or latest.record_hash != row.record_hash:
        raise ValueError("Recovery counterparty is historical; select the latest version")
    if base.counterparty_source_state(db, row) in {"stale", "source_unavailable"}:
        raise ValueError("Recovery counterparty source context is no longer current; revise the counterparty first")
    return row


def decision_context_state(db: Session, row: RecoveryPursuitDecision) -> str:
    claim = db.scalar(
        select(Claim).where(
            Claim.id == row.claim_id,
            Claim.organization_id == row.organization_id,
        )
    )
    if claim is None:
        return "source_unavailable"
    counterparty = _counterparty_by_id(db, claim=claim, counterparty_id=row.counterparty_id)
    if counterparty is None:
        return "source_unavailable"
    latest = base._latest_counterparty(db, claim=claim, counterparty_key=counterparty.counterparty_key)
    if latest is None:
        return "source_unavailable"
    if latest.id != counterparty.id or latest.record_hash != counterparty.record_hash:
        return "stale"
    source_state = base.counterparty_source_state(db, counterparty)
    if source_state in {"stale", "source_unavailable"}:
        return source_state
    return source_state


def current_decisions(db: Session, *, claim: Claim) -> list[RecoveryPursuitDecision]:
    rows = list(
        db.scalars(
            select(RecoveryPursuitDecision)
            .where(
                RecoveryPursuitDecision.organization_id == claim.organization_id,
                RecoveryPursuitDecision.claim_id == claim.id,
            )
            .order_by(RecoveryPursuitDecision.decision_key.asc(), RecoveryPursuitDecision.version.asc())
        )
    )
    current: dict[UUID, RecoveryPursuitDecision] = {}
    for row in rows:
        current[row.decision_key] = row
    return list(current.values())


def decision_history(db: Session, *, claim: Claim, decision_key: UUID) -> list[RecoveryPursuitDecision]:
    return list(
        db.scalars(
            select(RecoveryPursuitDecision)
            .where(
                RecoveryPursuitDecision.organization_id == claim.organization_id,
                RecoveryPursuitDecision.claim_id == claim.id,
                RecoveryPursuitDecision.decision_key == decision_key,
            )
            .order_by(RecoveryPursuitDecision.version.desc())
        )
    )


def action_history(db: Session, *, claim: Claim, decision_key: UUID) -> list[RecoveryActionLog]:
    return list(
        db.scalars(
            select(RecoveryActionLog)
            .where(
                RecoveryActionLog.organization_id == claim.organization_id,
                RecoveryActionLog.claim_id == claim.id,
                RecoveryActionLog.decision_key == decision_key,
            )
            .order_by(RecoveryActionLog.action_number.desc())
        )
    )


def _decision_hash_payload(
    *,
    claim: Claim,
    key: UUID,
    version: int,
    previous_hash: str | None,
    counterparty: RecoveryCounterparty,
    payload: RecoveryPursuitDecisionWrite,
    user: User,
    decided_at: datetime,
) -> dict:
    return {
        "claim_id": str(claim.id),
        "decision_key": str(key),
        "version": version,
        "previous_decision_hash": previous_hash,
        "counterparty_record_id": str(counterparty.id),
        "counterparty_record_hash": counterparty.record_hash,
        "disposition": payload.disposition,
        "rationale": payload.rationale.strip(),
        "basis_reference": payload.basis_reference.strip(),
        "next_review_date": payload.next_review_date.isoformat() if payload.next_review_date else None,
        "decided_by_id": str(user.id),
        "decided_at": decided_at.isoformat(),
        "authority_boundary": "human_recovery_disposition_only",
    }


def _create_decision_version(
    db: Session,
    *,
    claim: Claim,
    user: User,
    payload: RecoveryPursuitDecisionWrite,
    key: UUID,
    version: int,
    previous: RecoveryPursuitDecision | None,
) -> RecoveryPursuitDecision:
    counterparty = _current_counterparty(db, claim=claim, counterparty_id=payload.counterparty_id)
    if previous is not None:
        previous_counterparty = _counterparty_by_id(db, claim=claim, counterparty_id=previous.counterparty_id)
        if previous_counterparty is None or previous_counterparty.counterparty_key != counterparty.counterparty_key:
            raise ValueError("A recovery decision revision must remain on the same logical counterparty path")

    now = datetime.now(UTC)
    previous_hash = previous.decision_hash if previous else None
    row = RecoveryPursuitDecision(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        decision_key=key,
        version=version,
        supersedes_id=previous.id if previous else None,
        counterparty_id=counterparty.id,
        decided_by_id=user.id,
        disposition=payload.disposition,
        rationale=payload.rationale.strip(),
        basis_reference=payload.basis_reference.strip(),
        next_review_date=payload.next_review_date,
        previous_decision_hash=previous_hash,
        decision_hash=_hash(
            _decision_hash_payload(
                claim=claim,
                key=key,
                version=version,
                previous_hash=previous_hash,
                counterparty=counterparty,
                payload=payload,
                user=user,
                decided_at=now,
            )
        ),
        decided_at=now,
    )
    db.add(row)
    db.flush()
    return row


def create_decision(
    db: Session,
    *,
    claim: Claim,
    user: User,
    payload: RecoveryPursuitDecisionWrite,
) -> RecoveryPursuitDecision:
    base._lock_claim(db, claim)
    counterparty = _current_counterparty(db, claim=claim, counterparty_id=payload.counterparty_id)
    for existing in current_decisions(db, claim=claim):
        linked = _counterparty_by_id(db, claim=claim, counterparty_id=existing.counterparty_id)
        if linked is not None and linked.counterparty_key == counterparty.counterparty_key:
            raise ValueError("A recovery decision path already exists for this counterparty; revise the existing decision")

    key = uuid4()
    row = _create_decision_version(
        db,
        claim=claim,
        user=user,
        payload=payload,
        key=key,
        version=1,
        previous=None,
    )
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="CREATE_RECOVERY_PURSUIT_DECISION",
        entity_type="recovery_pursuit_decision",
        entity_id=row.id,
        new_values={
            "decision_key": str(row.decision_key),
            "version": row.version,
            "disposition": row.disposition,
            "decision_hash": row.decision_hash,
        },
        details="Explicit human recovery disposition recorded; no liability, entitlement or recoverability finding made.",
    )
    db.commit()
    db.refresh(row)
    return row


def revise_decision(
    db: Session,
    *,
    claim: Claim,
    user: User,
    decision_key: UUID,
    payload: RecoveryPursuitDecisionRevisionWrite,
) -> RecoveryPursuitDecision:
    base._lock_claim(db, claim)
    previous = _latest_decision(db, claim=claim, decision_key=decision_key)
    if previous is None:
        raise ValueError("Recovery decision path not found")
    if previous.decision_hash != payload.expected_decision_hash:
        raise ValueError("Recovery decision changed; reload the latest version before revising")

    row = _create_decision_version(
        db,
        claim=claim,
        user=user,
        payload=payload,
        key=decision_key,
        version=previous.version + 1,
        previous=previous,
    )
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="REVISE_RECOVERY_PURSUIT_DECISION",
        entity_type="recovery_pursuit_decision",
        entity_id=row.id,
        old_values={
            "decision_id": str(previous.id),
            "version": previous.version,
            "disposition": previous.disposition,
            "decision_hash": previous.decision_hash,
        },
        new_values={
            "decision_key": str(row.decision_key),
            "version": row.version,
            "disposition": row.disposition,
            "decision_hash": row.decision_hash,
        },
        details="New immutable human recovery decision version recorded; prior decision remains historical.",
    )
    db.commit()
    db.refresh(row)
    return row


def append_action(
    db: Session,
    *,
    claim: Claim,
    user: User,
    decision_key: UUID,
    payload: RecoveryActionLogWrite,
) -> RecoveryActionLog:
    base._lock_claim(db, claim)
    decision = _latest_decision(db, claim=claim, decision_key=decision_key)
    if decision is None:
        raise ValueError("Recovery decision path not found")
    if payload.decision_hash != decision.decision_hash:
        raise ValueError("Recovery decision changed; reload the latest version before adding an action")
    if decision_context_state(db, decision) in {"stale", "source_unavailable"}:
        raise ValueError("Recovery decision context is stale; deliberately revise the decision before adding new actions")

    previous = db.scalar(
        select(RecoveryActionLog)
        .where(
            RecoveryActionLog.organization_id == claim.organization_id,
            RecoveryActionLog.claim_id == claim.id,
            RecoveryActionLog.decision_key == decision_key,
        )
        .order_by(RecoveryActionLog.action_number.desc())
        .limit(1)
    )
    number = previous.action_number + 1 if previous else 1
    now = datetime.now(UTC)
    action_payload = {
        "claim_id": str(claim.id),
        "decision_key": str(decision_key),
        "decision_id": str(decision.id),
        "decision_hash": decision.decision_hash,
        "action_number": number,
        "action_type": payload.action_type,
        "direction": payload.direction,
        "occurred_on": payload.occurred_on.isoformat(),
        "summary": payload.summary.strip(),
        "source_reference": payload.source_reference.strip(),
        "external_status": payload.external_status.strip() if payload.external_status else None,
        "external_response_date": (
            payload.external_response_date.isoformat() if payload.external_response_date else None
        ),
        "previous_action_hash": previous.action_hash if previous else None,
        "created_by_id": str(user.id),
        "created_at": now.isoformat(),
        "authority_boundary": "human_action_record_only",
    }
    row = RecoveryActionLog(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        decision_key=decision_key,
        decision_id=decision.id,
        created_by_id=user.id,
        action_number=number,
        action_type=payload.action_type,
        direction=payload.direction,
        occurred_on=payload.occurred_on,
        summary=payload.summary.strip(),
        source_reference=payload.source_reference.strip(),
        external_status=payload.external_status.strip() if payload.external_status else None,
        external_response_date=payload.external_response_date,
        previous_action_hash=previous.action_hash if previous else None,
        action_hash=_hash(action_payload),
        created_at=now,
    )
    db.add(row)
    db.flush()
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="APPEND_RECOVERY_ACTION",
        entity_type="recovery_pursuit_decision",
        entity_id=decision.id,
        new_values={
            "action_id": str(row.id),
            "action_number": row.action_number,
            "action_type": row.action_type,
            "action_hash": row.action_hash,
        },
        details="Append-only human recovery action/correspondence record created; platform made no demand or settlement decision.",
    )
    db.commit()
    db.refresh(row)
    return row


def action_response(row: RecoveryActionLog) -> dict:
    return {
        "id": row.id,
        "decision_key": row.decision_key,
        "decision_id": row.decision_id,
        "created_by_id": row.created_by_id,
        "action_number": row.action_number,
        "action_type": row.action_type,
        "direction": row.direction,
        "occurred_on": row.occurred_on,
        "summary": row.summary,
        "source_reference": row.source_reference,
        "external_status": row.external_status,
        "external_response_date": row.external_response_date,
        "previous_action_hash": row.previous_action_hash,
        "action_hash": row.action_hash,
        "created_at": row.created_at,
    }


def decision_response(db: Session, *, claim: Claim, row: RecoveryPursuitDecision) -> dict:
    counterparty = _counterparty_by_id(db, claim=claim, counterparty_id=row.counterparty_id)
    actions = action_history(db, claim=claim, decision_key=row.decision_key)
    return {
        "id": row.id,
        "decision_key": row.decision_key,
        "version": row.version,
        "supersedes_id": row.supersedes_id,
        "counterparty_id": row.counterparty_id,
        "counterparty_name": counterparty.name if counterparty else "Unavailable counterparty",
        "counterparty_role": counterparty.role if counterparty else "Unavailable",
        "decided_by_id": row.decided_by_id,
        "disposition": row.disposition,
        "rationale": row.rationale,
        "basis_reference": row.basis_reference,
        "next_review_date": row.next_review_date,
        "previous_decision_hash": row.previous_decision_hash,
        "decision_hash": row.decision_hash,
        "context_state_status": decision_context_state(db, row),
        "decided_at": row.decided_at,
        "actions": [action_response(action) for action in actions],
    }

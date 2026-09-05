from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.documents.models import Document, DocumentMalwareScanStatus, DocumentProcessingStatus
from app.modules.recovery_timebar.models import RecoveryCounterparty, TimebarScenario, TimebarScenarioReview
from app.modules.recovery_timebar.schemas import (
    RecoveryCounterpartyRevisionWrite,
    RecoveryCounterpartyWrite,
    TimebarScenarioRevisionWrite,
    TimebarScenarioReviewWrite,
    TimebarScenarioWrite,
)
from app.modules.recovery_timebar.service_core import _add_period, _hash
from app.modules.users.models import User

MATURITY_DISCLAIMER = (
    "Counterparties and time-bar scenarios are human-created review context, not findings of liability, entitlement, "
    "recoverability or law. Candidate deadlines are calendar arithmetic only from explicit human inputs. Governing law, "
    "legal rule, anchor event, period, extension/tolling effect and any authoritative deadline require human/legal review."
)


def _lock_claim(db: Session, claim: Claim) -> Claim:
    locked = db.scalar(
        select(Claim).where(
            Claim.id == claim.id,
            Claim.organization_id == claim.organization_id,
        ).with_for_update()
    )
    if locked is None:
        raise ValueError("Claim no longer exists")
    return locked


def _usable_current_document(db: Session, *, claim: Claim, document_id: UUID) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == claim.organization_id,
            Document.claim_id == claim.id,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        raise ValueError("Source document does not belong to this claim")
    if not document.is_current:
        raise ValueError("Source document is superseded; select the current document version")
    if document.processing_status != DocumentProcessingStatus.PROCESSED:
        raise ValueError("Source document must be fully processed before it can bind a recovery/time-bar scenario")
    if document.malware_scan_status not in {
        DocumentMalwareScanStatus.CLEAN,
        DocumentMalwareScanStatus.LEGACY_UNSCANNED,
    }:
        raise ValueError("Source document is not currently usable")
    return document


def _document_snapshot(document: Document | None) -> dict:
    if document is None:
        return {
            "source_document_id": None,
            "source_document_family_id": None,
            "source_document_version": None,
            "source_document_hash": None,
        }
    return {
        "source_document_id": document.id,
        "source_document_family_id": document.document_family_id,
        "source_document_version": document.version_number,
        "source_document_hash": document.file_hash,
    }


def _source_state_status(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    source_document_id: UUID | None,
    source_document_family_id: UUID | None,
    source_document_version: int | None,
    source_document_hash: str | None,
) -> str:
    if source_document_id is None:
        return "reference_only"
    original = db.scalar(
        select(Document).where(
            Document.id == source_document_id,
            Document.organization_id == organization_id,
            Document.claim_id == claim_id,
        )
    )
    if original is None:
        return "source_unavailable"
    current = db.scalar(
        select(Document).where(
            Document.organization_id == organization_id,
            Document.claim_id == claim_id,
            Document.document_family_id == source_document_family_id,
            Document.is_current.is_(True),
            Document.deleted_at.is_(None),
        )
    )
    if current is None:
        return "source_unavailable"
    if (
        current.id == source_document_id
        and current.version_number == source_document_version
        and current.file_hash == source_document_hash
        and current.processing_status == DocumentProcessingStatus.PROCESSED
        and current.malware_scan_status
        in {DocumentMalwareScanStatus.CLEAN, DocumentMalwareScanStatus.LEGACY_UNSCANNED}
    ):
        return "current"
    return "stale"


def _latest_counterparty(db: Session, *, claim: Claim, counterparty_key: UUID) -> RecoveryCounterparty | None:
    return db.scalar(
        select(RecoveryCounterparty)
        .where(
            RecoveryCounterparty.organization_id == claim.organization_id,
            RecoveryCounterparty.claim_id == claim.id,
            RecoveryCounterparty.counterparty_key == counterparty_key,
        )
        .order_by(RecoveryCounterparty.version.desc())
        .limit(1)
    )


def _latest_scenario(db: Session, *, claim: Claim, scenario_key: UUID) -> TimebarScenario | None:
    return db.scalar(
        select(TimebarScenario)
        .where(
            TimebarScenario.organization_id == claim.organization_id,
            TimebarScenario.claim_id == claim.id,
            TimebarScenario.scenario_key == scenario_key,
        )
        .order_by(TimebarScenario.version.desc())
        .limit(1)
    )


def _latest_review(db: Session, scenario_id: UUID) -> TimebarScenarioReview | None:
    return db.scalar(
        select(TimebarScenarioReview)
        .where(TimebarScenarioReview.scenario_id == scenario_id)
        .order_by(TimebarScenarioReview.review_number.desc())
        .limit(1)
    )


def _counterparty_payload(
    *,
    claim: Claim,
    key: UUID,
    version: int,
    previous_hash: str | None,
    payload: RecoveryCounterpartyWrite,
    document: Document | None,
    user: User,
    created_at: datetime,
) -> dict:
    return {
        "claim_id": str(claim.id),
        "counterparty_key": str(key),
        "version": version,
        "previous_record_hash": previous_hash,
        "name": payload.name.strip(),
        "role": payload.role.strip(),
        "allegation_basis": payload.allegation_basis.strip(),
        "source_reference": payload.source_reference.strip(),
        "source_document": {
            "id": str(document.id) if document else None,
            "family_id": str(document.document_family_id) if document else None,
            "version": document.version_number if document else None,
            "file_hash": document.file_hash if document else None,
        },
        "created_by_id": str(user.id),
        "created_at": created_at.isoformat(),
        "authority_boundary": "human_allegation_context_only",
    }


def create_counterparty(
    db: Session, *, claim: Claim, user: User, payload: RecoveryCounterpartyWrite
) -> RecoveryCounterparty:
    _lock_claim(db, claim)
    document = (
        _usable_current_document(db, claim=claim, document_id=payload.source_document_id)
        if payload.source_document_id
        else None
    )
    key = uuid4()
    now = datetime.now(UTC)
    hash_payload = _counterparty_payload(
        claim=claim,
        key=key,
        version=1,
        previous_hash=None,
        payload=payload,
        document=document,
        user=user,
        created_at=now,
    )
    row = RecoveryCounterparty(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        counterparty_key=key,
        version=1,
        supersedes_id=None,
        created_by_id=user.id,
        name=payload.name.strip(),
        role=payload.role.strip(),
        allegation_basis=payload.allegation_basis.strip(),
        source_reference=payload.source_reference.strip(),
        **_document_snapshot(document),
        record_hash=_hash(hash_payload),
        created_at=now,
    )
    db.add(row)
    db.flush()
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="CREATE_RECOVERY_COUNTERPARTY",
        entity_type="recovery_counterparty",
        entity_id=row.id,
        new_values={"counterparty_key": str(key), "version": 1, "record_hash": row.record_hash},
        details="Human-created potential recovery counterparty context; no liability finding made.",
    )
    db.commit()
    db.refresh(row)
    return row


def revise_counterparty(
    db: Session,
    *,
    claim: Claim,
    user: User,
    counterparty_key: UUID,
    payload: RecoveryCounterpartyRevisionWrite,
) -> RecoveryCounterparty:
    _lock_claim(db, claim)
    previous = _latest_counterparty(db, claim=claim, counterparty_key=counterparty_key)
    if previous is None:
        raise ValueError("Recovery counterparty not found")
    if previous.record_hash != payload.expected_record_hash:
        raise ValueError("Recovery counterparty changed; reload the latest version before revising")
    document = (
        _usable_current_document(db, claim=claim, document_id=payload.source_document_id)
        if payload.source_document_id
        else None
    )
    now = datetime.now(UTC)
    version = previous.version + 1
    hash_payload = _counterparty_payload(
        claim=claim,
        key=counterparty_key,
        version=version,
        previous_hash=previous.record_hash,
        payload=payload,
        document=document,
        user=user,
        created_at=now,
    )
    row = RecoveryCounterparty(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        counterparty_key=counterparty_key,
        version=version,
        supersedes_id=previous.id,
        created_by_id=user.id,
        name=payload.name.strip(),
        role=payload.role.strip(),
        allegation_basis=payload.allegation_basis.strip(),
        source_reference=payload.source_reference.strip(),
        **_document_snapshot(document),
        record_hash=_hash(hash_payload),
        created_at=now,
    )
    db.add(row)
    db.flush()
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="REVISE_RECOVERY_COUNTERPARTY",
        entity_type="recovery_counterparty",
        entity_id=row.id,
        old_values={"record_id": str(previous.id), "record_hash": previous.record_hash, "version": previous.version},
        new_values={"counterparty_key": str(counterparty_key), "version": version, "record_hash": row.record_hash},
        details="New immutable counterparty version recorded; prior allegation context preserved.",
    )
    db.commit()
    db.refresh(row)
    return row


def _scenario_candidate(payload: TimebarScenarioWrite):
    candidate = _add_period(payload.anchor_date, payload.period_value, payload.period_unit)
    if payload.extension_value is not None and payload.extension_value > 0:
        candidate = _add_period(candidate, payload.extension_value, payload.extension_unit or "days")
    return candidate


def _validate_counterparty_reference(db: Session, *, claim: Claim, counterparty_id: UUID | None) -> RecoveryCounterparty | None:
    if counterparty_id is None:
        return None
    row = db.scalar(
        select(RecoveryCounterparty).where(
            RecoveryCounterparty.id == counterparty_id,
            RecoveryCounterparty.organization_id == claim.organization_id,
            RecoveryCounterparty.claim_id == claim.id,
        )
    )
    if row is None:
        raise ValueError("Counterparty record does not belong to this claim")
    latest = _latest_counterparty(db, claim=claim, counterparty_key=row.counterparty_key)
    if latest is None or latest.id != row.id:
        raise ValueError("Counterparty record is historical; select the latest counterparty version")
    return row


def _scenario_hash_payload(
    *,
    claim: Claim,
    key: UUID,
    version: int,
    previous_hash: str | None,
    payload: TimebarScenarioWrite,
    document: Document | None,
    counterparty: RecoveryCounterparty | None,
    candidate_deadline,
    user: User,
    created_at: datetime,
) -> dict:
    return {
        "claim_id": str(claim.id),
        "scenario_key": str(key),
        "version": version,
        "previous_scenario_hash": previous_hash,
        "title": payload.title.strip(),
        "legal_basis": payload.legal_basis.strip(),
        "source_reference": payload.source_reference.strip(),
        "source_document": {
            "id": str(document.id) if document else None,
            "family_id": str(document.document_family_id) if document else None,
            "version": document.version_number if document else None,
            "file_hash": document.file_hash if document else None,
        },
        "counterparty_record_id": str(counterparty.id) if counterparty else None,
        "counterparty_record_hash": counterparty.record_hash if counterparty else None,
        "anchor_date": payload.anchor_date.isoformat(),
        "period_value": payload.period_value,
        "period_unit": payload.period_unit,
        "extension_value": payload.extension_value,
        "extension_unit": payload.extension_unit,
        "extension_basis": payload.extension_basis.strip() if payload.extension_basis else None,
        "assumptions": payload.assumptions.strip(),
        "candidate_deadline": candidate_deadline.isoformat(),
        "created_by_id": str(user.id),
        "created_at": created_at.isoformat(),
        "authority_boundary": "calendar_arithmetic_only",
    }


def _create_scenario_version(
    db: Session,
    *,
    claim: Claim,
    user: User,
    payload: TimebarScenarioWrite,
    key: UUID,
    version: int,
    previous: TimebarScenario | None,
) -> TimebarScenario:
    document = (
        _usable_current_document(db, claim=claim, document_id=payload.source_document_id)
        if payload.source_document_id
        else None
    )
    counterparty = _validate_counterparty_reference(db, claim=claim, counterparty_id=payload.counterparty_id)
    candidate_deadline = _scenario_candidate(payload)
    now = datetime.now(UTC)
    hash_payload = _scenario_hash_payload(
        claim=claim,
        key=key,
        version=version,
        previous_hash=previous.scenario_hash if previous else None,
        payload=payload,
        document=document,
        counterparty=counterparty,
        candidate_deadline=candidate_deadline,
        user=user,
        created_at=now,
    )
    row = TimebarScenario(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        scenario_key=key,
        version=version,
        supersedes_id=previous.id if previous else None,
        created_by_id=user.id,
        counterparty_id=counterparty.id if counterparty else None,
        title=payload.title.strip(),
        legal_basis=payload.legal_basis.strip(),
        source_reference=payload.source_reference.strip(),
        **_document_snapshot(document),
        anchor_date=payload.anchor_date,
        period_value=payload.period_value,
        period_unit=payload.period_unit,
        extension_value=payload.extension_value,
        extension_unit=payload.extension_unit,
        extension_basis=payload.extension_basis.strip() if payload.extension_basis else None,
        assumptions=payload.assumptions.strip(),
        candidate_deadline=candidate_deadline,
        scenario_hash=_hash(hash_payload),
        created_at=now,
    )
    db.add(row)
    db.flush()
    return row


def create_scenario(db: Session, *, claim: Claim, user: User, payload: TimebarScenarioWrite) -> TimebarScenario:
    _lock_claim(db, claim)
    key = uuid4()
    row = _create_scenario_version(db, claim=claim, user=user, payload=payload, key=key, version=1, previous=None)
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="CREATE_TIMEBAR_SCENARIO",
        entity_type="timebar_scenario",
        entity_id=row.id,
        new_values={
            "scenario_key": str(key),
            "version": 1,
            "candidate_deadline": row.candidate_deadline.isoformat(),
            "scenario_hash": row.scenario_hash,
        },
        details="Human-defined alternative time-bar scenario created; candidate deadline is non-authoritative calendar arithmetic.",
    )
    db.commit()
    db.refresh(row)
    return row


def revise_scenario(
    db: Session,
    *,
    claim: Claim,
    user: User,
    scenario_key: UUID,
    payload: TimebarScenarioRevisionWrite,
) -> TimebarScenario:
    _lock_claim(db, claim)
    previous = _latest_scenario(db, claim=claim, scenario_key=scenario_key)
    if previous is None:
        raise ValueError("Time-bar scenario not found")
    if previous.scenario_hash != payload.expected_scenario_hash:
        raise ValueError("Time-bar scenario changed; reload the latest version before revising")
    row = _create_scenario_version(
        db,
        claim=claim,
        user=user,
        payload=payload,
        key=scenario_key,
        version=previous.version + 1,
        previous=previous,
    )
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="REVISE_TIMEBAR_SCENARIO",
        entity_type="timebar_scenario",
        entity_id=row.id,
        old_values={"scenario_id": str(previous.id), "version": previous.version, "scenario_hash": previous.scenario_hash},
        new_values={
            "scenario_key": str(scenario_key),
            "version": row.version,
            "candidate_deadline": row.candidate_deadline.isoformat(),
            "scenario_hash": row.scenario_hash,
        },
        details="New immutable time-bar scenario version created; prior reviewed versions remain historical.",
    )
    db.commit()
    db.refresh(row)
    return row


def review_scenario(
    db: Session,
    *,
    claim: Claim,
    user: User,
    scenario_id: UUID,
    payload: TimebarScenarioReviewWrite,
) -> TimebarScenarioReview:
    _lock_claim(db, claim)
    scenario = db.scalar(
        select(TimebarScenario).where(
            TimebarScenario.id == scenario_id,
            TimebarScenario.organization_id == claim.organization_id,
            TimebarScenario.claim_id == claim.id,
        )
    )
    if scenario is None:
        raise ValueError("Time-bar scenario not found")
    latest = _latest_scenario(db, claim=claim, scenario_key=scenario.scenario_key)
    if latest is None or latest.id != scenario.id:
        raise ValueError("Time-bar scenario is historical; review the latest version instead")
    if payload.scenario_hash != scenario.scenario_hash:
        raise ValueError("Scenario hash does not match the immutable scenario under review")
    source_status = scenario_source_state(db, scenario)
    if source_status in {"stale", "source_unavailable"}:
        raise ValueError("Scenario source is no longer current; create a new scenario version before review")

    previous = _latest_review(db, scenario.id)
    number = previous.review_number + 1 if previous else 1
    confirmed_deadline = scenario.candidate_deadline if payload.action == "confirm" else payload.confirmed_deadline
    now = datetime.now(UTC)
    review_payload = {
        "scenario_id": str(scenario.id),
        "scenario_hash": scenario.scenario_hash,
        "review_number": number,
        "action": payload.action,
        "confirmed_deadline": confirmed_deadline.isoformat() if confirmed_deadline else None,
        "note": payload.note.strip(),
        "source_reference": payload.source_reference.strip() if payload.source_reference else None,
        "previous_review_hash": previous.review_hash if previous else None,
        "reviewed_by_id": str(user.id),
        "reviewed_at": now.isoformat(),
        "authority_boundary": "human_legal_review",
    }
    row = TimebarScenarioReview(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        scenario_id=scenario.id,
        reviewed_by_id=user.id,
        scenario_hash=scenario.scenario_hash,
        review_number=number,
        action=payload.action,
        confirmed_deadline=confirmed_deadline,
        note=payload.note.strip(),
        source_reference=payload.source_reference.strip() if payload.source_reference else None,
        previous_review_hash=previous.review_hash if previous else None,
        review_hash=_hash(review_payload),
        reviewed_at=now,
    )
    db.add(row)
    db.flush()
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="REVIEW_TIMEBAR_SCENARIO",
        entity_type="timebar_scenario",
        entity_id=scenario.id,
        new_values={
            "review_id": str(row.id),
            "review_number": number,
            "action": payload.action,
            "confirmed_deadline": confirmed_deadline.isoformat() if confirmed_deadline else None,
            "review_hash": row.review_hash,
        },
        details="Human/legal time-bar review recorded separately from the non-authoritative computed candidate deadline.",
    )
    db.commit()
    db.refresh(row)
    return row


def counterparty_source_state(db: Session, row: RecoveryCounterparty) -> str:
    return _source_state_status(
        db,
        organization_id=row.organization_id,
        claim_id=row.claim_id,
        source_document_id=row.source_document_id,
        source_document_family_id=row.source_document_family_id,
        source_document_version=row.source_document_version,
        source_document_hash=row.source_document_hash,
    )


def scenario_source_state(db: Session, row: TimebarScenario) -> str:
    return _source_state_status(
        db,
        organization_id=row.organization_id,
        claim_id=row.claim_id,
        source_document_id=row.source_document_id,
        source_document_family_id=row.source_document_family_id,
        source_document_version=row.source_document_version,
        source_document_hash=row.source_document_hash,
    )


def counterparty_response(db: Session, row: RecoveryCounterparty) -> dict:
    return {
        "id": row.id,
        "counterparty_key": row.counterparty_key,
        "version": row.version,
        "supersedes_id": row.supersedes_id,
        "created_by_id": row.created_by_id,
        "name": row.name,
        "role": row.role,
        "allegation_basis": row.allegation_basis,
        "source_reference": row.source_reference,
        "source_document_id": row.source_document_id,
        "source_document_family_id": row.source_document_family_id,
        "source_document_version": row.source_document_version,
        "source_document_hash": row.source_document_hash,
        "source_state_status": counterparty_source_state(db, row),
        "record_hash": row.record_hash,
        "created_at": row.created_at,
    }


def review_response(row: TimebarScenarioReview) -> dict:
    return {
        "id": row.id,
        "scenario_id": row.scenario_id,
        "reviewed_by_id": row.reviewed_by_id,
        "scenario_hash": row.scenario_hash,
        "review_number": row.review_number,
        "action": row.action,
        "confirmed_deadline": row.confirmed_deadline,
        "note": row.note,
        "source_reference": row.source_reference,
        "previous_review_hash": row.previous_review_hash,
        "review_hash": row.review_hash,
        "reviewed_at": row.reviewed_at,
    }


def scenario_response(db: Session, row: TimebarScenario) -> dict:
    latest_review = _latest_review(db, row.id)
    return {
        "id": row.id,
        "scenario_key": row.scenario_key,
        "version": row.version,
        "supersedes_id": row.supersedes_id,
        "created_by_id": row.created_by_id,
        "counterparty_id": row.counterparty_id,
        "title": row.title,
        "legal_basis": row.legal_basis,
        "source_reference": row.source_reference,
        "source_document_id": row.source_document_id,
        "source_document_family_id": row.source_document_family_id,
        "source_document_version": row.source_document_version,
        "source_document_hash": row.source_document_hash,
        "source_state_status": scenario_source_state(db, row),
        "anchor_date": row.anchor_date,
        "period_value": row.period_value,
        "period_unit": row.period_unit,
        "extension_value": row.extension_value,
        "extension_unit": row.extension_unit,
        "extension_basis": row.extension_basis,
        "assumptions": row.assumptions,
        "candidate_deadline": row.candidate_deadline,
        "scenario_hash": row.scenario_hash,
        "created_at": row.created_at,
        "latest_review": review_response(latest_review) if latest_review else None,
    }


def current_counterparties(db: Session, *, claim: Claim) -> list[RecoveryCounterparty]:
    rows = list(
        db.scalars(
            select(RecoveryCounterparty)
            .where(
                RecoveryCounterparty.organization_id == claim.organization_id,
                RecoveryCounterparty.claim_id == claim.id,
            )
            .order_by(RecoveryCounterparty.counterparty_key.asc(), RecoveryCounterparty.version.asc())
        )
    )
    current: dict[UUID, RecoveryCounterparty] = {}
    for row in rows:
        current[row.counterparty_key] = row
    return list(current.values())


def current_scenarios(db: Session, *, claim: Claim) -> list[TimebarScenario]:
    rows = list(
        db.scalars(
            select(TimebarScenario)
            .where(
                TimebarScenario.organization_id == claim.organization_id,
                TimebarScenario.claim_id == claim.id,
            )
            .order_by(TimebarScenario.scenario_key.asc(), TimebarScenario.version.asc())
        )
    )
    current: dict[UUID, TimebarScenario] = {}
    for row in rows:
        current[row.scenario_key] = row
    return list(current.values())


def counterparty_history(db: Session, *, claim: Claim, counterparty_key: UUID) -> list[RecoveryCounterparty]:
    return list(
        db.scalars(
            select(RecoveryCounterparty)
            .where(
                RecoveryCounterparty.organization_id == claim.organization_id,
                RecoveryCounterparty.claim_id == claim.id,
                RecoveryCounterparty.counterparty_key == counterparty_key,
            )
            .order_by(RecoveryCounterparty.version.desc())
        )
    )


def scenario_history(db: Session, *, claim: Claim, scenario_key: UUID) -> list[TimebarScenario]:
    return list(
        db.scalars(
            select(TimebarScenario)
            .where(
                TimebarScenario.organization_id == claim.organization_id,
                TimebarScenario.claim_id == claim.id,
                TimebarScenario.scenario_key == scenario_key,
            )
            .order_by(TimebarScenario.version.desc())
        )
    )

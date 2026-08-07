from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import (
    Claim,
    ClaimPriority,
    ClaimReferenceSequence,
    ClaimStatus,
    ClaimType,
)
from app.modules.claims.schemas import ClaimCreate, ClaimUpdate
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel


class ClaimValidationError(ValueError):
    pass


class ClaimNotFoundError(LookupError):
    pass


class InvalidStatusTransitionError(ValueError):
    pass


class ClaimPermissionError(PermissionError):
    pass


_REFERENCE_PREFIX = {ClaimType.HULL_MACHINERY: "HM"}

_ALLOWED_TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    ClaimStatus.NEW: {ClaimStatus.TRIAGE, ClaimStatus.AWAITING_DOCUMENTS, ClaimStatus.ON_HOLD, ClaimStatus.WITHDRAWN},
    ClaimStatus.TRIAGE: {ClaimStatus.AWAITING_DOCUMENTS, ClaimStatus.INVESTIGATION, ClaimStatus.ON_HOLD, ClaimStatus.REJECTED, ClaimStatus.WITHDRAWN},
    ClaimStatus.AWAITING_DOCUMENTS: {ClaimStatus.INVESTIGATION, ClaimStatus.TECHNICAL_REVIEW, ClaimStatus.ON_HOLD, ClaimStatus.WITHDRAWN},
    ClaimStatus.INVESTIGATION: {ClaimStatus.AWAITING_DOCUMENTS, ClaimStatus.TECHNICAL_REVIEW, ClaimStatus.FINANCIAL_REVIEW, ClaimStatus.COVERAGE_REVIEW, ClaimStatus.ON_HOLD, ClaimStatus.LITIGATION},
    ClaimStatus.TECHNICAL_REVIEW: {ClaimStatus.AWAITING_DOCUMENTS, ClaimStatus.INVESTIGATION, ClaimStatus.FINANCIAL_REVIEW, ClaimStatus.COVERAGE_REVIEW, ClaimStatus.ON_HOLD},
    ClaimStatus.FINANCIAL_REVIEW: {ClaimStatus.TECHNICAL_REVIEW, ClaimStatus.COVERAGE_REVIEW, ClaimStatus.NEGOTIATION, ClaimStatus.SETTLEMENT, ClaimStatus.ON_HOLD},
    ClaimStatus.COVERAGE_REVIEW: {ClaimStatus.AWAITING_DOCUMENTS, ClaimStatus.INVESTIGATION, ClaimStatus.NEGOTIATION, ClaimStatus.SETTLEMENT, ClaimStatus.REJECTED, ClaimStatus.LITIGATION, ClaimStatus.ON_HOLD},
    ClaimStatus.NEGOTIATION: {ClaimStatus.FINANCIAL_REVIEW, ClaimStatus.COVERAGE_REVIEW, ClaimStatus.SETTLEMENT, ClaimStatus.LITIGATION, ClaimStatus.ON_HOLD},
    ClaimStatus.SETTLEMENT: {ClaimStatus.RECOVERY, ClaimStatus.CLOSED, ClaimStatus.LITIGATION},
    ClaimStatus.RECOVERY: {ClaimStatus.CLOSED},
    ClaimStatus.ON_HOLD: {ClaimStatus.TRIAGE, ClaimStatus.AWAITING_DOCUMENTS, ClaimStatus.INVESTIGATION, ClaimStatus.TECHNICAL_REVIEW, ClaimStatus.FINANCIAL_REVIEW, ClaimStatus.COVERAGE_REVIEW, ClaimStatus.NEGOTIATION, ClaimStatus.SETTLEMENT, ClaimStatus.RECOVERY},
    ClaimStatus.LITIGATION: {ClaimStatus.NEGOTIATION, ClaimStatus.SETTLEMENT, ClaimStatus.RECOVERY, ClaimStatus.CLOSED},
    ClaimStatus.REJECTED: {ClaimStatus.CLOSED},
    ClaimStatus.WITHDRAWN: {ClaimStatus.CLOSED},
    ClaimStatus.CLOSED: set(),
}

_MANAGER_ONLY_DESTINATIONS = {
    ClaimStatus.SETTLEMENT,
    ClaimStatus.RECOVERY,
    ClaimStatus.CLOSED,
    ClaimStatus.REJECTED,
    ClaimStatus.WITHDRAWN,
    ClaimStatus.LITIGATION,
}


def _next_reference_number(db: Session, *, organization_id: UUID, year: int, claim_type: ClaimType) -> int:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = (
            pg_insert(ClaimReferenceSequence)
            .values(
                organization_id=organization_id,
                year=year,
                claim_type=claim_type,
                last_number=1,
            )
            .on_conflict_do_update(
                constraint="uq_claim_ref_seq_org_year_type",
                set_={"last_number": ClaimReferenceSequence.last_number + 1},
            )
            .returning(ClaimReferenceSequence.last_number)
        )
        return int(db.scalar(stmt))

    # SQLite/test fallback; PostgreSQL production path above is atomic.
    sequence = db.scalar(
        select(ClaimReferenceSequence).where(
            ClaimReferenceSequence.organization_id == organization_id,
            ClaimReferenceSequence.year == year,
            ClaimReferenceSequence.claim_type == claim_type,
        )
    )
    if sequence is None:
        sequence = ClaimReferenceSequence(
            organization_id=organization_id,
            year=year,
            claim_type=claim_type,
            last_number=1,
        )
        db.add(sequence)
        db.flush()
        return 1
    sequence.last_number += 1
    db.flush()
    return sequence.last_number


def generate_claim_reference(db: Session, *, organization_id: UUID, incident_date: date, claim_type: ClaimType) -> str:
    number = _next_reference_number(
        db,
        organization_id=organization_id,
        year=incident_date.year,
        claim_type=claim_type,
    )
    return f"MCRI-{_REFERENCE_PREFIX[claim_type]}-{incident_date.year}-{number:04d}"


def get_vessel_for_tenant(db: Session, *, vessel_id: UUID, organization_id: UUID) -> Vessel | None:
    return db.scalar(
        select(Vessel).where(
            Vessel.id == vessel_id,
            Vessel.organization_id == organization_id,
            Vessel.deleted_at.is_(None),
        )
    )


def get_handler_for_tenant(db: Session, *, handler_id: UUID, organization_id: UUID) -> User | None:
    return db.scalar(
        select(User).where(
            User.id == handler_id,
            User.organization_id == organization_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )


def _claim_query_for_tenant(*, organization_id: UUID):
    return (
        select(Claim)
        .options(joinedload(Claim.vessel), joinedload(Claim.handler))
        .where(Claim.organization_id == organization_id, Claim.deleted_at.is_(None))
    )


def get_claim(db: Session, *, claim_id: UUID, organization_id: UUID) -> Claim:
    claim = db.scalar(_claim_query_for_tenant(organization_id=organization_id).where(Claim.id == claim_id))
    if claim is None:
        raise ClaimNotFoundError("Claim not found")
    return claim


def create_claim(db: Session, *, organization_id: UUID, current_user: User, payload: ClaimCreate) -> Claim:
    vessel = get_vessel_for_tenant(db, vessel_id=payload.vessel_id, organization_id=organization_id)
    if vessel is None:
        raise ClaimValidationError("Vessel is unavailable in this organization")

    handler = None
    if payload.handler_id is not None:
        if current_user.role not in {UserRole.ADMIN, UserRole.CLAIMS_MANAGER}:
            raise ClaimPermissionError("Only an administrator or claims manager can assign a handler")
        handler = get_handler_for_tenant(db, handler_id=payload.handler_id, organization_id=organization_id)
        if handler is None:
            raise ClaimValidationError("Handler is unavailable in this organization")

    reference = generate_claim_reference(
        db,
        organization_id=organization_id,
        incident_date=payload.incident_date,
        claim_type=payload.claim_type,
    )
    claim = Claim(
        organization_id=organization_id,
        vessel_id=vessel.id,
        handler_id=handler.id if handler else None,
        claim_reference=reference,
        external_reference=payload.external_reference.strip() if payload.external_reference else None,
        claim_type=payload.claim_type,
        claim_subtype=payload.claim_subtype,
        status=ClaimStatus.NEW,
        priority=payload.priority,
        incident_date=payload.incident_date,
        notification_date=payload.notification_date,
        incident_description=payload.incident_description.strip(),
        estimated_loss=payload.estimated_loss,
        currency=payload.currency,
    )
    db.add(claim)
    db.flush()
    return get_claim(db, claim_id=claim.id, organization_id=organization_id)


def list_claims(
    db: Session,
    *,
    organization_id: UUID,
    status: ClaimStatus | None = None,
    priority: ClaimPriority | None = None,
    vessel_id: UUID | None = None,
    handler_id: UUID | None = None,
    incident_from: date | None = None,
    incident_to: date | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Claim], int]:
    filters = [Claim.organization_id == organization_id, Claim.deleted_at.is_(None)]
    if status is not None:
        filters.append(Claim.status == status)
    if priority is not None:
        filters.append(Claim.priority == priority)
    if vessel_id is not None:
        filters.append(Claim.vessel_id == vessel_id)
    if handler_id is not None:
        filters.append(Claim.handler_id == handler_id)
    if incident_from is not None:
        filters.append(Claim.incident_date >= incident_from)
    if incident_to is not None:
        filters.append(Claim.incident_date <= incident_to)

    base = select(Claim).join(Vessel, Vessel.id == Claim.vessel_id).where(*filters)
    if search:
        pattern = f"%{search.strip()}%"
        base = base.where(
            or_(
                Claim.claim_reference.ilike(pattern),
                Claim.external_reference.ilike(pattern),
                Vessel.name.ilike(pattern),
                Vessel.imo_number.ilike(pattern),
            )
        )

    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    query = (
        base.options(joinedload(Claim.vessel), joinedload(Claim.handler))
        .order_by(Claim.incident_date.desc(), Claim.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(query).unique()), total


def update_claim_details(
    db: Session,
    *,
    claim: Claim,
    organization_id: UUID,
    payload: ClaimUpdate,
) -> tuple[Claim, dict, dict]:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return claim, {}, {}

    if "vessel_id" in changes:
        vessel = get_vessel_for_tenant(db, vessel_id=changes["vessel_id"], organization_id=organization_id)
        if vessel is None:
            raise ClaimValidationError("Vessel is unavailable in this organization")

    old_values: dict[str, object] = {}
    new_values: dict[str, object] = {}
    for field, value in changes.items():
        old = getattr(claim, field)
        if old == value:
            continue
        old_values[field] = str(old) if old is not None else None
        new_values[field] = str(value) if value is not None else None
        setattr(claim, field, value)

    db.flush()
    return get_claim(db, claim_id=claim.id, organization_id=organization_id), old_values, new_values


def assign_claim(
    db: Session,
    *,
    claim: Claim,
    organization_id: UUID,
    handler_id: UUID | None,
) -> tuple[Claim, UUID | None]:
    old_handler_id = claim.handler_id
    if handler_id is None:
        claim.handler = None
    else:
        handler = get_handler_for_tenant(db, handler_id=handler_id, organization_id=organization_id)
        if handler is None:
            raise ClaimValidationError("Handler is unavailable in this organization")
        if handler.role not in {UserRole.CLAIMS_HANDLER, UserRole.CLAIMS_MANAGER, UserRole.ADMIN}:
            raise ClaimValidationError("Selected user cannot handle claims")
        # Assign the relationship, not only the FK, so the in-session representation
        # cannot retain a stale previously-loaded handler.
        claim.handler = handler
    db.flush()
    return get_claim(db, claim_id=claim.id, organization_id=organization_id), old_handler_id


def change_claim_status(
    db: Session,
    *,
    claim: Claim,
    new_status: ClaimStatus,
    current_user: User,
) -> ClaimStatus:
    old_status = claim.status
    if new_status == old_status:
        return old_status
    if new_status not in _ALLOWED_TRANSITIONS[old_status]:
        raise InvalidStatusTransitionError(f"Status cannot move from {old_status.value} to {new_status.value}")
    if new_status in _MANAGER_ONLY_DESTINATIONS and current_user.role not in {
        UserRole.ADMIN,
        UserRole.CLAIMS_MANAGER,
    }:
        raise ClaimPermissionError(f"Only a claims manager or administrator can move a claim to {new_status.value}")
    claim.status = new_status
    db.flush()
    return old_status


def update_current_reserve(db: Session, *, claim: Claim, amount: Decimal) -> Decimal | None:
    old_reserve = claim.current_reserve
    claim.current_reserve = amount
    db.flush()
    return old_reserve


def list_claim_facts(db: Session, *, claim_id: UUID, organization_id: UUID) -> list[ClaimFact]:
    # Reuse claim access semantics so facts cannot disclose a deleted/cross-tenant claim.
    get_claim(db, claim_id=claim_id, organization_id=organization_id)
    return list(
        db.scalars(
            select(ClaimFact)
            .where(ClaimFact.organization_id == organization_id, ClaimFact.claim_id == claim_id)
            .order_by(ClaimFact.field_path.asc())
        )
    )

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claim_intelligence.domain_catalog import (
    DOMAIN_CATALOG_VERSION,
    domain_catalog_payload,
    validate_domain_classification,
)
from app.modules.claim_intelligence.models import ClaimDomainClassification
from app.modules.claim_intelligence.schemas import ClaimDomainClassificationWrite
from app.modules.claims.models import Claim
from app.modules.users.models import User


def _classification_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def get_domain_catalog() -> dict:
    return domain_catalog_payload()


def list_domain_classifications(
    db: Session,
    *,
    claim: Claim,
) -> list[ClaimDomainClassification]:
    return list(
        db.scalars(
            select(ClaimDomainClassification)
            .where(
                ClaimDomainClassification.organization_id == claim.organization_id,
                ClaimDomainClassification.claim_id == claim.id,
            )
            .order_by(ClaimDomainClassification.classification_number.desc())
        )
    )


def get_current_domain_classification(
    db: Session,
    *,
    claim: Claim,
) -> ClaimDomainClassification | None:
    return db.scalar(
        select(ClaimDomainClassification)
        .where(
            ClaimDomainClassification.organization_id == claim.organization_id,
            ClaimDomainClassification.claim_id == claim.id,
        )
        .order_by(ClaimDomainClassification.classification_number.desc())
        .limit(1)
    )


def create_domain_classification(
    db: Session,
    *,
    claim: Claim,
    user: User,
    payload: ClaimDomainClassificationWrite,
) -> ClaimDomainClassification:
    if not payload.confirm_classification:
        raise ValueError("Explicit human confirmation is required to classify the claim domain")

    note = payload.note.strip()
    if len(note) < 20:
        raise ValueError("Classification note must contain at least 20 non-whitespace characters")

    incident_code, component_code, failure_mode = validate_domain_classification(
        payload.incident_code,
        payload.component_code,
        payload.failure_mode,
    )

    locked_claim = db.scalar(
        select(Claim)
        .where(
            Claim.id == claim.id,
            Claim.organization_id == user.organization_id,
        )
        .with_for_update()
    )
    if locked_claim is None:
        raise ValueError("Claim is no longer available for classification")

    previous = get_current_domain_classification(db, claim=locked_claim)
    classification_number = (previous.classification_number + 1) if previous is not None else 1
    previous_hash = previous.classification_hash if previous is not None else None

    hash_payload = {
        "organization_id": locked_claim.organization_id,
        "claim_id": locked_claim.id,
        "catalog_version": DOMAIN_CATALOG_VERSION,
        "classification_number": classification_number,
        "incident_code": incident_code,
        "component_code": component_code,
        "failure_mode": failure_mode,
        "classification_note": note,
        "classified_by_id": user.id,
        "supersedes_classification_id": previous.id if previous is not None else None,
        "previous_classification_hash": previous_hash,
    }
    classification_hash = _classification_hash(hash_payload)

    row = ClaimDomainClassification(
        organization_id=locked_claim.organization_id,
        claim_id=locked_claim.id,
        catalog_version=DOMAIN_CATALOG_VERSION,
        classification_number=classification_number,
        incident_code=incident_code,
        component_code=component_code,
        failure_mode=failure_mode,
        classification_note=note,
        classified_by_id=user.id,
        supersedes_classification_id=previous.id if previous is not None else None,
        previous_classification_hash=previous_hash,
        classification_hash=classification_hash,
    )
    db.add(row)
    db.flush()

    write_audit_log(
        db,
        organization_id=locked_claim.organization_id,
        user_id=user.id,
        action="CLASSIFY_CLAIM_DOMAIN",
        entity_type="claim_domain_classification",
        entity_id=row.id,
        new_values={
            "claim_id": str(locked_claim.id),
            "catalog_version": DOMAIN_CATALOG_VERSION,
            "classification_number": classification_number,
            "incident_code": incident_code,
            "component_code": component_code,
            "failure_mode_supplied": failure_mode is not None,
            "classification_note_supplied": True,
            "supersedes_prior_classification": previous is not None,
        },
        details=(
            "Human-confirmed claim domain context recorded. Classification note and integrity hashes are excluded "
            "from audit metadata. This action does not execute rules, build intelligence or make a substantive claim decision."
        ),
    )
    db.commit()
    db.refresh(row)
    return row

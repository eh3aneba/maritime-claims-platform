from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.claims.retention_schemas import LegalHoldProposalRead
from app.modules.claims.retention_service import RetentionNotFoundError
from app.modules.claims.retention_signal_schemas import (
    PreservationSignalPayload,
    PreservationSignalProfileCreate,
    PreservationSignalProfileRead,
    PreservationSignalProfileSecretRead,
    PreservationSignalProfileUpdate,
    PreservationSignalReceipt,
)
from app.modules.claims.retention_signal_service import (
    PreservationSignalAuthError,
    PreservationSignalConflictError,
    create_signal_profile,
    get_signal_profile,
    get_signal_profile_public,
    ingest_signed_preservation_signal,
    list_signal_profiles,
    rotate_signal_profile_secret,
    update_signal_profile,
    verify_preservation_signal,
)

router = APIRouter(prefix="/claims/retention/signal-intake", tags=["retention"])
MAX_SIGNAL_BODY_BYTES = 16_384


@router.post(
    "/profiles",
    response_model=PreservationSignalProfileSecretRead,
    status_code=status.HTTP_201_CREATED,
)
def create_signal_profile_endpoint(
    payload: PreservationSignalProfileCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> PreservationSignalProfileSecretRead:
    try:
        profile, signing_secret = create_signal_profile(
            db,
            user=current_user,
            name=payload.name,
            enabled=payload.enabled,
            allowed_hold_sources=list(payload.allowed_hold_sources),
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="CREATE_PRESERVATION_SIGNAL_PROFILE",
            entity_type="preservation_signal_profile",
            entity_id=profile.id,
            new_values={
                "name": profile.name,
                "enabled": profile.enabled,
                "allowed_hold_sources": profile.allowed_hold_sources,
                "secret_version": profile.secret_version,
                "secret_material_persisted": False,
            },
        )
        db.commit()
        db.refresh(profile)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A preservation signal profile with this name already exists",
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return PreservationSignalProfileSecretRead(
        profile=PreservationSignalProfileRead.model_validate(profile),
        signing_secret=signing_secret,
    )


@router.get("/profiles", response_model=list[PreservationSignalProfileRead])
def list_signal_profiles_endpoint(
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[PreservationSignalProfileRead]:
    return [
        PreservationSignalProfileRead.model_validate(profile)
        for profile in list_signal_profiles(db, organization_id=current_user.organization_id)
    ]


@router.patch("/profiles/{profile_id}", response_model=PreservationSignalProfileRead)
def update_signal_profile_endpoint(
    profile_id: UUID,
    payload: PreservationSignalProfileUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> PreservationSignalProfileRead:
    try:
        profile = get_signal_profile(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
        )
        old_values = {
            "enabled": profile.enabled,
            "allowed_hold_sources": list(profile.allowed_hold_sources),
        }
        update_signal_profile(
            profile,
            user=current_user,
            enabled=payload.enabled,
            allowed_hold_sources=(
                list(payload.allowed_hold_sources)
                if payload.allowed_hold_sources is not None
                else None
            ),
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="UPDATE_PRESERVATION_SIGNAL_PROFILE",
            entity_type="preservation_signal_profile",
            entity_id=profile.id,
            old_values=old_values,
            new_values={
                "enabled": profile.enabled,
                "allowed_hold_sources": profile.allowed_hold_sources,
            },
        )
        db.commit()
        db.refresh(profile)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return PreservationSignalProfileRead.model_validate(profile)


@router.post(
    "/profiles/{profile_id}/rotate-secret",
    response_model=PreservationSignalProfileSecretRead,
)
def rotate_signal_profile_secret_endpoint(
    profile_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> PreservationSignalProfileSecretRead:
    try:
        profile = get_signal_profile(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
        )
        signing_secret = rotate_signal_profile_secret(profile, user=current_user)
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="ROTATE_PRESERVATION_SIGNAL_SECRET",
            entity_type="preservation_signal_profile",
            entity_id=profile.id,
            new_values={
                "secret_version": profile.secret_version,
                "previous_secret_valid_until": (
                    profile.previous_secret_valid_until.isoformat()
                    if profile.previous_secret_valid_until
                    else None
                ),
                "secret_material_persisted": False,
            },
        )
        db.commit()
        db.refresh(profile)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PreservationSignalProfileSecretRead(
        profile=PreservationSignalProfileRead.model_validate(profile),
        signing_secret=signing_secret,
    )


@router.post(
    "/profiles/{profile_id}/signals",
    response_model=PreservationSignalReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_preservation_signal_endpoint(
    profile_id: UUID,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    signal_id: Annotated[str, Header(alias="X-MCRI-Signal-ID")],
    signal_timestamp: Annotated[str, Header(alias="X-MCRI-Signal-Timestamp")],
    signal_key_version: Annotated[str, Header(alias="X-MCRI-Signal-Key-Version")],
    signal_signature: Annotated[str, Header(alias="X-MCRI-Signal-Signature")],
) -> PreservationSignalReceipt:
    raw_body = await request.body()
    if not raw_body or len(raw_body) > MAX_SIGNAL_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Preservation signal body is empty or exceeds the allowed size",
        )
    try:
        profile = get_signal_profile_public(db, profile_id=profile_id)
        verify_preservation_signal(
            profile,
            raw_body=raw_body,
            timestamp_header=signal_timestamp,
            key_version_header=signal_key_version,
            signature_header=signal_signature,
        )
        payload = PreservationSignalPayload.model_validate_json(raw_body)
        proposal, created = ingest_signed_preservation_signal(
            db,
            profile=profile,
            signal_id=signal_id,
            payload=payload,
        )
        db.commit()
        db.refresh(proposal)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal profile not found") from exc
    except PreservationSignalAuthError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid preservation signal payload",
        ) from exc
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found") from exc
    except (PreservationSignalConflictError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Preservation signal conflicts with existing signal identity",
        ) from exc

    read = LegalHoldProposalRead.model_validate(proposal)
    return PreservationSignalReceipt(
        proposal_id=read.id,
        claim_id=read.claim_id,
        proposal_status=read.status,
        created=created,
        source_kind=read.source_kind,
        source_ref_fingerprint=read.source_ref_fingerprint,
        source_payload_hash=read.source_payload_hash,
    )

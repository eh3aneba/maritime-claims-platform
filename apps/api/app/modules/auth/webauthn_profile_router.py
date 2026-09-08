from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import require_roles
from app.modules.auth.webauthn_profile import (
    create_webauthn_rp_profile,
    get_current_webauthn_rp_profile,
    list_webauthn_rp_profiles,
)
from app.modules.auth.webauthn_schemas import (
    WebAuthnRelyingPartyProfileCreate,
    WebAuthnRelyingPartyProfileRead,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/auth/webauthn", tags=["authentication", "mfa", "webauthn"])


@router.post(
    "/rp-profiles",
    response_model=WebAuthnRelyingPartyProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_webauthn_rp_profile_as_admin(
    payload: WebAuthnRelyingPartyProfileCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> WebAuthnRelyingPartyProfileRead:
    try:
        profile = create_webauthn_rp_profile(
            db,
            organization_id=current_user.organization_id,
            rp_id=payload.rp_id,
            rp_name=payload.rp_name,
            allowed_origins=list(payload.allowed_origins),
            user_verification=payload.user_verification,
            attestation=payload.attestation,
            created_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="WEBAUTHN_RP_PROFILE_PINNED",
            entity_type="webauthn_relying_party_profile",
            entity_id=profile.id,
            new_values={
                "profile_number": profile.profile_number,
                "rp_id": profile.rp_id,
                "allowed_origins": profile.allowed_origins,
                "user_verification": profile.user_verification,
                "attestation": profile.attestation,
                "profile_hash": profile.profile_hash,
            },
        )
        db.commit()
        db.refresh(profile)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WebAuthn relying-party profile conflicts with current tenant lineage",
        ) from exc
    return WebAuthnRelyingPartyProfileRead.model_validate(profile)


@router.get(
    "/rp-profile",
    response_model=WebAuthnRelyingPartyProfileRead,
)
def current_webauthn_rp_profile_as_admin(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> WebAuthnRelyingPartyProfileRead:
    profile = get_current_webauthn_rp_profile(
        db,
        organization_id=current_user.organization_id,
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WebAuthn relying-party profile not found",
        )
    return WebAuthnRelyingPartyProfileRead.model_validate(profile)


@router.get(
    "/rp-profiles",
    response_model=list[WebAuthnRelyingPartyProfileRead],
)
def webauthn_rp_profile_history_as_admin(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[WebAuthnRelyingPartyProfileRead]:
    return [
        WebAuthnRelyingPartyProfileRead.model_validate(profile)
        for profile in list_webauthn_rp_profiles(
            db,
            organization_id=current_user.organization_id,
        )
    ]

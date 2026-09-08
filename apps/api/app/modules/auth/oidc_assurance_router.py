from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import require_roles
from app.modules.auth.oidc_assurance import (
    create_oidc_mfa_assurance_profile,
    get_current_oidc_mfa_assurance_profile,
    list_oidc_mfa_assurance_profiles,
)
from app.modules.auth.oidc_assurance_schemas import (
    OidcMfaAssuranceProfileCreate,
    OidcMfaAssuranceProfileRead,
)
from app.modules.auth.oidc_trust import get_oidc_provider_for_tenant
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["authentication"])


def _oidc_provider_or_error(*, provider_id: UUID, organization_id: UUID, db: Session):
    provider = get_oidc_provider_for_tenant(
        db,
        provider_id=provider_id,
        organization_id=organization_id,
    )
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identity provider not found")
    if provider.protocol != "oidc":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OIDC MFA assurance requires an OIDC identity provider",
        )
    if not provider.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OIDC identity provider must be enabled",
        )
    return provider


@router.post(
    "/identity-providers/{provider_id}/oidc-mfa-assurance-profiles",
    response_model=OidcMfaAssuranceProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_oidc_mfa_assurance_profile_as_admin(
    provider_id: UUID,
    payload: OidcMfaAssuranceProfileCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> OidcMfaAssuranceProfileRead:
    provider = _oidc_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    try:
        profile = create_oidc_mfa_assurance_profile(
            db,
            provider=provider,
            enabled=payload.enabled,
            accepted_amr_values=list(payload.accepted_amr_values),
            accepted_acr_values=list(payload.accepted_acr_values),
            created_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="OIDC_MFA_ASSURANCE_PROFILE_PINNED",
            entity_type="oidc_mfa_assurance_profile",
            entity_id=profile.id,
            new_values={
                "provider_id": str(provider.id),
                "trust_profile_id": str(profile.trust_profile_id),
                "trust_profile_number": profile.trust_profile_number,
                "trust_profile_hash": profile.trust_profile_hash,
                "profile_number": profile.profile_number,
                "profile_hash": profile.profile_hash,
                "enabled": profile.enabled,
                "accepted_amr_count": len(profile.accepted_amr_values),
                "accepted_acr_count": len(profile.accepted_acr_values),
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
            detail="OIDC MFA assurance profile conflicts with current provider lineage",
        ) from exc
    return OidcMfaAssuranceProfileRead.model_validate(profile)


@router.get(
    "/identity-providers/{provider_id}/oidc-mfa-assurance-profile",
    response_model=OidcMfaAssuranceProfileRead,
)
def current_oidc_mfa_assurance_profile_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> OidcMfaAssuranceProfileRead:
    provider = _oidc_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    profile = get_current_oidc_mfa_assurance_profile(
        db,
        organization_id=current_user.organization_id,
        provider_id=provider.id,
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OIDC MFA assurance profile not found")
    return OidcMfaAssuranceProfileRead.model_validate(profile)


@router.get(
    "/identity-providers/{provider_id}/oidc-mfa-assurance-profiles",
    response_model=list[OidcMfaAssuranceProfileRead],
)
def oidc_mfa_assurance_profile_history_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[OidcMfaAssuranceProfileRead]:
    provider = _oidc_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    profiles = list_oidc_mfa_assurance_profiles(
        db,
        organization_id=current_user.organization_id,
        provider_id=provider.id,
    )
    return [OidcMfaAssuranceProfileRead.model_validate(profile) for profile in profiles]

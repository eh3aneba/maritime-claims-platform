from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import require_roles
from app.modules.auth.saml_assurance import (
    create_saml_mfa_assurance_profile,
    get_current_saml_mfa_assurance_profile,
    list_saml_mfa_assurance_profiles,
)
from app.modules.auth.saml_assurance_schemas import (
    SamlMfaAssuranceProfileCreate,
    SamlMfaAssuranceProfileRead,
)
from app.modules.auth.saml_trust import get_saml_provider_for_tenant
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["authentication"])


def _provider_or_error(*, provider_id: UUID, organization_id: UUID, db: Session):
    provider = get_saml_provider_for_tenant(
        db,
        provider_id=provider_id,
        organization_id=organization_id,
    )
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identity provider not found")
    if provider.protocol != "saml":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SAML MFA assurance requires a SAML identity provider",
        )
    if not provider.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SAML identity provider must be enabled",
        )
    return provider


@router.post(
    "/identity-providers/{provider_id}/saml-mfa-assurance-profiles",
    response_model=SamlMfaAssuranceProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_profile_as_admin(
    provider_id: UUID,
    payload: SamlMfaAssuranceProfileCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> SamlMfaAssuranceProfileRead:
    provider = _provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    try:
        profile = create_saml_mfa_assurance_profile(
            db,
            provider=provider,
            enabled=payload.enabled,
            accepted_authn_context_values=list(payload.accepted_authn_context_values),
            created_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="SAML_MFA_ASSURANCE_PROFILE_PINNED",
            entity_type="saml_mfa_assurance_profile",
            entity_id=profile.id,
            new_values={
                "provider_id": str(provider.id),
                "saml_profile_id": str(profile.saml_profile_id),
                "saml_profile_number": profile.saml_profile_number,
                "saml_profile_hash": profile.saml_profile_hash,
                "profile_number": profile.profile_number,
                "profile_hash": profile.profile_hash,
                "enabled": profile.enabled,
                "accepted_value_count": len(profile.accepted_authn_context_values),
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
            detail="SAML MFA assurance profile conflicts with current lineage",
        ) from exc
    return SamlMfaAssuranceProfileRead.model_validate(profile)


@router.get(
    "/identity-providers/{provider_id}/saml-mfa-assurance-profile",
    response_model=SamlMfaAssuranceProfileRead,
)
def current_profile_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> SamlMfaAssuranceProfileRead:
    _provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    profile = get_current_saml_mfa_assurance_profile(
        db,
        organization_id=current_user.organization_id,
        provider_id=provider_id,
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SAML MFA assurance profile not found")
    return SamlMfaAssuranceProfileRead.model_validate(profile)


@router.get(
    "/identity-providers/{provider_id}/saml-mfa-assurance-profiles",
    response_model=list[SamlMfaAssuranceProfileRead],
)
def profile_history_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[SamlMfaAssuranceProfileRead]:
    _provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    profiles = list_saml_mfa_assurance_profiles(
        db,
        organization_id=current_user.organization_id,
        provider_id=provider_id,
    )
    return [SamlMfaAssuranceProfileRead.model_validate(profile) for profile in profiles]

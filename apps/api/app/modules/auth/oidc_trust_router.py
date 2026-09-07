from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import require_roles
from app.modules.auth.oidc_trust import (
    create_oidc_trust_profile,
    get_current_oidc_trust_profile,
    get_oidc_provider_for_tenant,
    list_oidc_trust_profiles,
)
from app.modules.auth.schemas import OidcTrustProfileCreate, OidcTrustProfileRead
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["authentication"])


def _governed_oidc_provider_or_error(
    *,
    provider_id: UUID,
    organization_id: UUID,
    db: Session,
):
    provider = get_oidc_provider_for_tenant(
        db,
        provider_id=provider_id,
        organization_id=organization_id,
    )
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity provider not found",
        )
    if provider.protocol != "oidc":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OIDC trust profiles require an OIDC identity provider",
        )
    if not provider.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OIDC identity provider must be enabled",
        )
    return provider


@router.post(
    "/identity-providers/{provider_id}/oidc-trust-profiles",
    response_model=OidcTrustProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_oidc_trust_profile_as_admin(
    provider_id: UUID,
    payload: OidcTrustProfileCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> OidcTrustProfileRead:
    provider = _governed_oidc_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    try:
        profile = create_oidc_trust_profile(
            db,
            provider=provider,
            audience=payload.audience,
            jwks_uri=payload.jwks_uri,
            allowed_algorithms=list(payload.allowed_algorithms),
            created_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="OIDC_TRUST_PROFILE_PINNED",
            entity_type="oidc_trust_profile",
            entity_id=profile.id,
            new_values={
                "provider_id": str(provider.id),
                "profile_number": profile.profile_number,
                "profile_hash": profile.profile_hash,
            },
        )
        db.commit()
        db.refresh(profile)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OIDC trust profile conflicts with current provider lineage",
        ) from exc

    return OidcTrustProfileRead.model_validate(profile)


@router.get(
    "/identity-providers/{provider_id}/oidc-trust-profile",
    response_model=OidcTrustProfileRead,
)
def current_oidc_trust_profile_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> OidcTrustProfileRead:
    provider = _governed_oidc_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    profile = get_current_oidc_trust_profile(
        db,
        provider_id=provider.id,
        organization_id=current_user.organization_id,
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OIDC trust profile not found",
        )
    return OidcTrustProfileRead.model_validate(profile)


@router.get(
    "/identity-providers/{provider_id}/oidc-trust-profiles",
    response_model=list[OidcTrustProfileRead],
)
def oidc_trust_profile_history_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[OidcTrustProfileRead]:
    provider = _governed_oidc_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    profiles = list_oidc_trust_profiles(
        db,
        provider_id=provider.id,
        organization_id=current_user.organization_id,
    )
    return [OidcTrustProfileRead.model_validate(profile) for profile in profiles]

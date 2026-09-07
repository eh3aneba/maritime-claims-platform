from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import require_roles
from app.modules.auth.oidc_runtime import (
    create_oidc_runtime_profile,
    get_current_compatible_oidc_runtime_profile,
    list_oidc_runtime_profiles,
)
from app.modules.auth.oidc_trust import get_oidc_provider_for_tenant
from app.modules.auth.schemas import OidcRuntimeProfileCreate, OidcRuntimeProfileRead
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
    if provider.protocol != "oidc" or not provider.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Enabled OIDC identity provider is required",
        )
    return provider


@router.post(
    "/identity-providers/{provider_id}/oidc-runtime-profiles",
    response_model=OidcRuntimeProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_oidc_runtime_profile_as_admin(
    provider_id: UUID,
    payload: OidcRuntimeProfileCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> OidcRuntimeProfileRead:
    provider = _governed_oidc_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    try:
        runtime_profile = create_oidc_runtime_profile(
            db,
            provider=provider,
            authorization_endpoint=payload.authorization_endpoint,
            token_endpoint=payload.token_endpoint,
            redirect_uri=payload.redirect_uri,
            scopes=list(payload.scopes),
            client_auth_method=payload.client_auth_method,
            created_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="OIDC_RUNTIME_PROFILE_PINNED",
            entity_type="oidc_runtime_profile",
            entity_id=runtime_profile.id,
            new_values={
                "provider_id": str(provider.id),
                "trust_profile_id": str(runtime_profile.trust_profile_id),
                "trust_profile_number": runtime_profile.trust_profile_number,
                "trust_profile_hash": runtime_profile.trust_profile_hash,
                "runtime_profile_number": runtime_profile.runtime_profile_number,
                "runtime_profile_hash": runtime_profile.runtime_profile_hash,
                "client_auth_method": runtime_profile.client_auth_method,
            },
        )
        db.commit()
        db.refresh(runtime_profile)
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
            detail="OIDC runtime profile conflicts with current lineage",
        ) from exc

    return OidcRuntimeProfileRead.model_validate(runtime_profile)


@router.get(
    "/identity-providers/{provider_id}/oidc-runtime-profile",
    response_model=OidcRuntimeProfileRead,
)
def current_oidc_runtime_profile_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> OidcRuntimeProfileRead:
    provider = _governed_oidc_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    runtime_profile = get_current_compatible_oidc_runtime_profile(
        db,
        organization_id=current_user.organization_id,
        provider_id=provider.id,
    )
    if runtime_profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Compatible OIDC runtime profile not found",
        )
    return OidcRuntimeProfileRead.model_validate(runtime_profile)


@router.get(
    "/identity-providers/{provider_id}/oidc-runtime-profiles",
    response_model=list[OidcRuntimeProfileRead],
)
def oidc_runtime_profile_history_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[OidcRuntimeProfileRead]:
    provider = _governed_oidc_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    profiles = list_oidc_runtime_profiles(
        db,
        organization_id=current_user.organization_id,
        provider_id=provider.id,
    )
    return [OidcRuntimeProfileRead.model_validate(profile) for profile in profiles]

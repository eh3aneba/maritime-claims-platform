from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import require_roles
from app.modules.auth.saml_schemas import (
    SamlTrustRuntimeProfileCreate,
    SamlTrustRuntimeProfileRead,
)
from app.modules.auth.saml_trust import (
    create_saml_trust_runtime_profile,
    get_current_saml_trust_runtime_profile,
    get_saml_provider_for_tenant,
    list_saml_trust_runtime_profiles,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["authentication"])


def _governed_saml_provider_or_error(
    *,
    provider_id: UUID,
    organization_id: UUID,
    db: Session,
):
    provider = get_saml_provider_for_tenant(
        db,
        provider_id=provider_id,
        organization_id=organization_id,
    )
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity provider not found",
        )
    if provider.protocol != "saml":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SAML trust/runtime profiles require a SAML identity provider",
        )
    if not provider.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SAML identity provider must be enabled",
        )
    return provider


@router.post(
    "/identity-providers/{provider_id}/saml-trust-runtime-profiles",
    response_model=SamlTrustRuntimeProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_saml_trust_runtime_profile_as_admin(
    provider_id: UUID,
    payload: SamlTrustRuntimeProfileCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> SamlTrustRuntimeProfileRead:
    provider = _governed_saml_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    try:
        profile = create_saml_trust_runtime_profile(
            db,
            provider=provider,
            idp_sso_url=payload.idp_sso_url,
            sp_entity_id=payload.sp_entity_id,
            acs_url=payload.acs_url,
            authn_request_binding=payload.authn_request_binding,
            response_binding=payload.response_binding,
            allowed_signature_algorithms=list(payload.allowed_signature_algorithms),
            allowed_digest_algorithms=list(payload.allowed_digest_algorithms),
            idp_signing_certificate_pem=payload.idp_signing_certificate_pem,
            created_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="SAML_TRUST_RUNTIME_PROFILE_PINNED",
            entity_type="saml_trust_runtime_profile",
            entity_id=profile.id,
            new_values={
                "provider_id": str(provider.id),
                "profile_number": profile.profile_number,
                "certificate_sha256": profile.certificate_sha256,
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
            detail="SAML trust/runtime profile conflicts with current provider lineage",
        ) from exc

    return SamlTrustRuntimeProfileRead.model_validate(profile)


@router.get(
    "/identity-providers/{provider_id}/saml-trust-runtime-profile",
    response_model=SamlTrustRuntimeProfileRead,
)
def current_saml_trust_runtime_profile_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> SamlTrustRuntimeProfileRead:
    provider = _governed_saml_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    profile = get_current_saml_trust_runtime_profile(
        db,
        provider_id=provider.id,
        organization_id=current_user.organization_id,
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SAML trust/runtime profile not found",
        )
    return SamlTrustRuntimeProfileRead.model_validate(profile)


@router.get(
    "/identity-providers/{provider_id}/saml-trust-runtime-profiles",
    response_model=list[SamlTrustRuntimeProfileRead],
)
def saml_trust_runtime_profile_history_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[SamlTrustRuntimeProfileRead]:
    provider = _governed_saml_provider_or_error(
        provider_id=provider_id,
        organization_id=current_user.organization_id,
        db=db,
    )
    profiles = list_saml_trust_runtime_profiles(
        db,
        provider_id=provider.id,
        organization_id=current_user.organization_id,
    )
    return [SamlTrustRuntimeProfileRead.model_validate(profile) for profile in profiles]

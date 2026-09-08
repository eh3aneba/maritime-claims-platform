from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import require_roles
from app.modules.auth.scim import (
    ScimServiceContext,
    authenticate_scim_bearer_token,
    create_scim_provisioning_profile,
    get_current_scim_provisioning_profile,
    get_scim_token_for_tenant,
    issue_scim_provisioning_token,
    list_scim_provisioning_profiles,
    revoke_scim_provisioning_token,
)
from app.modules.auth.scim_schemas import (
    ScimProvisioningProfileCreate,
    ScimProvisioningProfileRead,
    ScimProvisioningTokenIssued,
    ScimProvisioningTokenRead,
)
from app.modules.users.models import User, UserRole

admin_router = APIRouter(prefix="/auth/scim-provisioning", tags=["authentication"])
service_router = APIRouter(prefix="/scim/v2", tags=["scim"])
scim_bearer_scheme = HTTPBearer(auto_error=False)


def get_scim_service_context(
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(scim_bearer_scheme),
    ],
) -> ScimServiceContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SCIM bearer authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    context = authenticate_scim_bearer_token(
        db,
        plaintext_token=credentials.credentials,
    )
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive SCIM provisioning credential",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return context


CurrentScimServiceContext = Annotated[ScimServiceContext, Depends(get_scim_service_context)]


@admin_router.post(
    "/profiles",
    response_model=ScimProvisioningProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_profile_as_admin(
    payload: ScimProvisioningProfileCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> ScimProvisioningProfileRead:
    try:
        profile = create_scim_provisioning_profile(
            db,
            organization_id=current_user.organization_id,
            client_name=payload.client_name,
            token_ttl_days=payload.token_ttl_days,
            enabled=payload.enabled,
            created_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="SCIM_PROVISIONING_PROFILE_PINNED",
            entity_type="scim_provisioning_profile",
            entity_id=profile.id,
            new_values={
                "profile_number": profile.profile_number,
                "profile_hash": profile.profile_hash,
                "previous_profile_hash": profile.previous_profile_hash,
                "client_name": profile.client_name,
                "service_base_path": profile.service_base_path,
                "token_ttl_days": profile.token_ttl_days,
                "enabled": profile.enabled,
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
            detail="SCIM provisioning profile conflicts with current lineage",
        ) from exc
    return ScimProvisioningProfileRead.model_validate(profile)


@admin_router.get(
    "/profiles",
    response_model=list[ScimProvisioningProfileRead],
)
def profile_history_as_admin(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[ScimProvisioningProfileRead]:
    profiles = list_scim_provisioning_profiles(
        db,
        organization_id=current_user.organization_id,
    )
    return [ScimProvisioningProfileRead.model_validate(profile) for profile in profiles]


@admin_router.get(
    "/profile",
    response_model=ScimProvisioningProfileRead,
)
def current_profile_as_admin(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> ScimProvisioningProfileRead:
    profile = get_current_scim_provisioning_profile(
        db,
        organization_id=current_user.organization_id,
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SCIM provisioning profile not found",
        )
    return ScimProvisioningProfileRead.model_validate(profile)


@admin_router.post(
    "/profiles/{profile_id}/tokens",
    response_model=ScimProvisioningTokenIssued,
    status_code=status.HTTP_201_CREATED,
)
def issue_token_as_admin(
    profile_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> ScimProvisioningTokenIssued:
    try:
        issued = issue_scim_provisioning_token(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            created_by_id=current_user.id,
        )
        record = issued.token_record
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="SCIM_PROVISIONING_TOKEN_ISSUED",
            entity_type="scim_provisioning_token",
            entity_id=record.id,
            new_values={
                "profile_id": str(record.profile_id),
                "profile_number": record.profile_number,
                "profile_hash": record.profile_hash,
                "token_prefix": record.token_prefix,
                "expires_at": record.expires_at.isoformat(),
            },
        )
        db.commit()
        db.refresh(record)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SCIM provisioning token conflicts with current credential state",
        ) from exc
    return ScimProvisioningTokenIssued(
        token=issued.plaintext_token,
        credential=ScimProvisioningTokenRead.model_validate(record),
    )


@admin_router.post(
    "/tokens/{token_id}/revoke",
    response_model=ScimProvisioningTokenRead,
)
def revoke_token_as_admin(
    token_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> ScimProvisioningTokenRead:
    token = get_scim_token_for_tenant(
        db,
        organization_id=current_user.organization_id,
        token_id=token_id,
    )
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SCIM provisioning token not found",
        )
    changed = revoke_scim_provisioning_token(
        token=token,
        revoked_by_id=current_user.id,
    )
    if changed:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="SCIM_PROVISIONING_TOKEN_REVOKED",
            entity_type="scim_provisioning_token",
            entity_id=token.id,
            new_values={
                "profile_id": str(token.profile_id),
                "token_prefix": token.token_prefix,
                "revocation_reason": token.revocation_reason,
            },
        )
        db.commit()
        db.refresh(token)
    return ScimProvisioningTokenRead.model_validate(token)


@service_router.get("/ServiceProviderConfig")
def service_provider_config(
    _: CurrentScimServiceContext,
) -> Response:
    return JSONResponse(
        media_type="application/scim+json",
        content={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "patch": {"supported": False},
            "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": False, "maxResults": 0},
            "changePassword": {"supported": False},
            "sort": {"supported": False},
            "etag": {"supported": False},
            "authenticationSchemes": [
                {
                    "type": "oauthbearertoken",
                    "name": "HTTP Bearer Token",
                    "description": "Locally issued tenant-scoped SCIM provisioning bearer token",
                    "specUri": "https://www.rfc-editor.org/rfc/rfc6750",
                    "primary": True,
                }
            ],
        },
    )

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import require_roles
from app.modules.auth.scim import (
    SCIM_LIST_SCHEMA,
    SCIM_USER_SCHEMA,
    ScimManagedUser,
    ScimServiceContext,
    authenticate_scim_bearer_token,
    cancel_scim_user_provisioning_grant,
    create_scim_provisioning_profile,
    create_scim_user_provisioning_grant,
    deactivate_scim_managed_user,
    get_current_scim_provisioning_profile,
    get_scim_managed_user,
    get_scim_token_for_tenant,
    get_scim_user_provisioning_grant,
    issue_scim_provisioning_token,
    list_scim_managed_users,
    list_scim_provisioning_profiles,
    list_scim_user_provisioning_grants,
    provision_scim_user,
    replace_scim_managed_user,
    revoke_scim_provisioning_token,
    scim_user_provisioning_is_enabled,
)
from app.modules.auth.scim_schemas import (
    ScimProvisioningProfileCreate,
    ScimProvisioningProfileRead,
    ScimProvisioningTokenIssued,
    ScimProvisioningTokenRead,
    ScimUserCreate,
    ScimUserProvisioningGrantCreate,
    ScimUserProvisioningGrantRead,
    ScimUserReplace,
)
from app.modules.users.models import User, UserRole

admin_router = APIRouter(prefix="/auth/scim-provisioning", tags=["authentication"])
service_router = APIRouter(prefix="/scim/v2", tags=["scim"])
scim_bearer_scheme = HTTPBearer(auto_error=False)
_SCIM_USERNAME_FILTER = re.compile(r'^userName\s+eq\s+"([^"]+)"$')


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


def _scim_error(status_code: int, detail: str, *, scim_type: str | None = None) -> JSONResponse:
    content: dict[str, object] = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "status": str(status_code),
        "detail": detail,
    }
    if scim_type is not None:
        content["scimType"] = scim_type
    return JSONResponse(
        status_code=status_code,
        media_type="application/scim+json",
        content=content,
    )


def _scim_user_resource(managed: ScimManagedUser) -> dict[str, object]:
    user = managed.user
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "id": str(user.id),
        "userName": user.email,
        "displayName": user.full_name,
        "active": user.is_active,
        "meta": {
            "resourceType": "User",
            "created": user.created_at.isoformat(),
            "lastModified": managed.binding.last_synced_at.isoformat(),
            "location": f"/api/v1/scim/v2/Users/{user.id}",
        },
    }


def _validate_user_schema(schemas: list[str]) -> JSONResponse | None:
    if schemas != [SCIM_USER_SCHEMA]:
        return _scim_error(
            status.HTTP_400_BAD_REQUEST,
            "Only the SCIM core User schema is supported",
            scim_type="invalidValue",
        )
    return None


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
            user_provisioning_enabled=payload.user_provisioning_enabled,
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
                "user_provisioning_enabled": profile.user_provisioning_enabled,
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


@admin_router.post(
    "/user-grants",
    response_model=ScimUserProvisioningGrantRead,
    status_code=status.HTTP_201_CREATED,
)
def create_user_grant_as_admin(
    payload: ScimUserProvisioningGrantCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> ScimUserProvisioningGrantRead:
    try:
        grant = create_scim_user_provisioning_grant(
            db,
            organization_id=current_user.organization_id,
            email=str(payload.email),
            role=payload.role,
            ttl_hours=payload.ttl_hours,
            created_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="SCIM_USER_PROVISIONING_GRANT_CREATED",
            entity_type="scim_user_provisioning_grant",
            entity_id=grant.id,
            new_values={
                "profile_id": str(grant.profile_id),
                "profile_number": grant.profile_number,
                "profile_hash": grant.profile_hash,
                "email_fingerprint": grant.email_fingerprint,
                "role": grant.role,
                "grant_hash": grant.grant_hash,
                "expires_at": grant.expires_at.isoformat(),
            },
        )
        db.commit()
        db.refresh(grant)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SCIM User provisioning grant conflicts with current state",
        ) from exc
    return ScimUserProvisioningGrantRead.model_validate(grant)


@admin_router.get(
    "/user-grants",
    response_model=list[ScimUserProvisioningGrantRead],
)
def user_grants_as_admin(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[ScimUserProvisioningGrantRead]:
    grants = list_scim_user_provisioning_grants(
        db,
        organization_id=current_user.organization_id,
    )
    return [ScimUserProvisioningGrantRead.model_validate(grant) for grant in grants]


@admin_router.post(
    "/user-grants/{grant_id}/cancel",
    response_model=ScimUserProvisioningGrantRead,
)
def cancel_user_grant_as_admin(
    grant_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> ScimUserProvisioningGrantRead:
    grant = get_scim_user_provisioning_grant(
        db,
        organization_id=current_user.organization_id,
        grant_id=grant_id,
    )
    if grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SCIM User grant not found")
    changed = cancel_scim_user_provisioning_grant(
        grant,
        cancelled_by_id=current_user.id,
    )
    if changed:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="SCIM_USER_PROVISIONING_GRANT_CANCELLED",
            entity_type="scim_user_provisioning_grant",
            entity_id=grant.id,
            new_values={"cancellation_reason": grant.cancellation_reason},
        )
        db.commit()
        db.refresh(grant)
    return ScimUserProvisioningGrantRead.model_validate(grant)


@service_router.get("/ServiceProviderConfig")
def service_provider_config(
    context: CurrentScimServiceContext,
) -> Response:
    user_capability = scim_user_provisioning_is_enabled(context)
    return JSONResponse(
        media_type="application/scim+json",
        content={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "patch": {"supported": False},
            "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": user_capability, "maxResults": 100 if user_capability else 0},
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


@service_router.post("/Users")
def create_scim_user(
    payload: ScimUserCreate,
    context: CurrentScimServiceContext,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    schema_error = _validate_user_schema(payload.schemas)
    if schema_error is not None:
        return schema_error
    try:
        managed = provision_scim_user(
            db,
            context=context,
            user_name=str(payload.user_name),
            display_name=payload.display_name,
            name=payload.name,
            active=payload.active,
            external_id=payload.external_id,
            roles_present="roles" in payload.model_fields_set,
            groups_present="groups" in payload.model_fields_set,
        )
        write_audit_log(
            db,
            organization_id=context.organization_id,
            user_id=None,
            action="SCIM_USER_PROVISIONED",
            entity_type="user",
            entity_id=managed.user.id,
            new_values={
                "profile_id": str(context.profile.id),
                "profile_number": context.profile.profile_number,
                "grant_id": str(managed.binding.grant_id),
                "role": managed.user.role.value,
                "active": managed.user.is_active,
                "user_name_fingerprint": managed.binding.user_name_fingerprint,
                "external_id_fingerprint": managed.binding.external_id_fingerprint,
            },
        )
        db.commit()
        db.refresh(managed.user)
        db.refresh(managed.binding)
    except PermissionError as exc:
        db.rollback()
        return _scim_error(status.HTTP_403_FORBIDDEN, str(exc))
    except ValueError as exc:
        db.rollback()
        return _scim_error(status.HTTP_409_CONFLICT, str(exc), scim_type="uniqueness")
    except IntegrityError:
        db.rollback()
        return _scim_error(
            status.HTTP_409_CONFLICT,
            "SCIM User conflicts with existing governed identity lineage",
            scim_type="uniqueness",
        )
    resource = _scim_user_resource(managed)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        media_type="application/scim+json",
        headers={"Location": resource["meta"]["location"]},
        content=resource,
    )


@service_router.get("/Users")
def list_scim_users(
    context: CurrentScimServiceContext,
    db: Annotated[Session, Depends(get_db)],
    filter_expression: Annotated[str | None, Query(alias="filter")] = None,
    start_index: Annotated[int, Query(alias="startIndex", ge=1)] = 1,
    count: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Response:
    if not scim_user_provisioning_is_enabled(context):
        return _scim_error(status.HTTP_403_FORBIDDEN, "SCIM User provisioning capability is disabled")
    user_name: str | None = None
    if filter_expression is not None:
        match = _SCIM_USERNAME_FILTER.fullmatch(filter_expression.strip())
        if match is None:
            return _scim_error(
                status.HTTP_400_BAD_REQUEST,
                "Only exact userName eq \"...\" filtering is supported",
                scim_type="invalidFilter",
            )
        user_name = match.group(1)
    managed_users = list_scim_managed_users(
        db,
        organization_id=context.organization_id,
        user_name=user_name,
        limit=count,
    )
    resources = [_scim_user_resource(managed) for managed in managed_users]
    return JSONResponse(
        media_type="application/scim+json",
        content={
            "schemas": [SCIM_LIST_SCHEMA],
            "totalResults": len(resources),
            "startIndex": start_index,
            "itemsPerPage": len(resources),
            "Resources": resources,
        },
    )


@service_router.get("/Users/{user_id}")
def get_scim_user(
    user_id: UUID,
    context: CurrentScimServiceContext,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not scim_user_provisioning_is_enabled(context):
        return _scim_error(status.HTTP_403_FORBIDDEN, "SCIM User provisioning capability is disabled")
    managed = get_scim_managed_user(
        db,
        organization_id=context.organization_id,
        user_id=user_id,
    )
    if managed is None:
        return _scim_error(status.HTTP_404_NOT_FOUND, "SCIM managed User not found")
    return JSONResponse(media_type="application/scim+json", content=_scim_user_resource(managed))


@service_router.put("/Users/{user_id}")
def replace_scim_user(
    user_id: UUID,
    payload: ScimUserReplace,
    context: CurrentScimServiceContext,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    schema_error = _validate_user_schema(payload.schemas)
    if schema_error is not None:
        return schema_error
    try:
        managed, revoked_sessions = replace_scim_managed_user(
            db,
            context=context,
            user_id=user_id,
            user_name=str(payload.user_name),
            display_name=payload.display_name,
            name=payload.name,
            active=payload.active,
            external_id=payload.external_id,
            external_id_present="external_id" in payload.model_fields_set,
            roles_present="roles" in payload.model_fields_set,
            groups_present="groups" in payload.model_fields_set,
        )
        write_audit_log(
            db,
            organization_id=context.organization_id,
            user_id=None,
            action="SCIM_USER_SYNCHRONIZED",
            entity_type="user",
            entity_id=managed.user.id,
            new_values={
                "active": managed.user.is_active,
                "role": managed.user.role.value,
                "revoked_sessions": revoked_sessions,
                "profile_id": str(context.profile.id),
            },
        )
        db.commit()
        db.refresh(managed.user)
        db.refresh(managed.binding)
    except PermissionError as exc:
        db.rollback()
        return _scim_error(status.HTTP_403_FORBIDDEN, str(exc))
    except LookupError as exc:
        db.rollback()
        return _scim_error(status.HTTP_404_NOT_FOUND, str(exc))
    except ValueError as exc:
        db.rollback()
        return _scim_error(status.HTTP_409_CONFLICT, str(exc), scim_type="mutability")
    return JSONResponse(media_type="application/scim+json", content=_scim_user_resource(managed))


@service_router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scim_user(
    user_id: UUID,
    context: CurrentScimServiceContext,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    try:
        managed, revoked_sessions = deactivate_scim_managed_user(
            db,
            context=context,
            user_id=user_id,
        )
        write_audit_log(
            db,
            organization_id=context.organization_id,
            user_id=None,
            action="SCIM_USER_DEACTIVATED",
            entity_type="user",
            entity_id=managed.user.id,
            new_values={
                "active": False,
                "revoked_sessions": revoked_sessions,
                "profile_id": str(context.profile.id),
            },
        )
        db.commit()
    except PermissionError as exc:
        db.rollback()
        return _scim_error(status.HTTP_403_FORBIDDEN, str(exc))
    except LookupError as exc:
        db.rollback()
        return _scim_error(status.HTTP_404_NOT_FOUND, str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)

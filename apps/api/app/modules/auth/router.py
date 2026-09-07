from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentAuthContext, CurrentUser, require_roles
from app.modules.auth.schemas import (
    AuthSessionRead,
    EnterpriseIdentityProviderCreate,
    EnterpriseIdentityProviderRead,
    ExternalIdentityBindingCreate,
    ExternalIdentityBindingRead,
    LoginRequest,
    LoginResponse,
)
from app.modules.auth.service import (
    authenticate_user,
    create_auth_session,
    create_external_identity_binding,
    create_identity_provider,
    get_auth_session_for_tenant,
    get_external_identity_binding_for_tenant,
    get_identity_provider_for_tenant,
    get_user_for_tenant,
    list_external_identity_bindings,
    list_identity_providers,
    revoke_auth_session,
    revoke_external_identity_binding,
    set_identity_provider_enabled,
)
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    user = authenticate_user(
        db,
        organization_slug=payload.organization_slug,
        email=str(payload.email),
        password=payload.password,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid organization, email, or password",
        )

    auth_session = create_auth_session(db, user=user)
    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="LOGIN_SUCCESS",
        entity_type="auth_session",
        entity_id=auth_session.id,
        new_values={
            "identity_source": auth_session.identity_source,
            "auth_method": auth_session.auth_method,
        },
    )
    db.commit()
    db.refresh(user)

    token = create_access_token(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role.value,
        session_id=auth_session.id,
        identity_source=auth_session.identity_source,
        auth_method=auth_session.auth_method,
    )
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.app_env.lower() in {"staging", "production"},
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return LoginResponse(access_token=token, user=UserRead.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> None:
    revoke_auth_session(
        auth_session=current_context.session,
        revoked_by_id=current_context.user.id,
        reason="logout",
    )
    write_audit_log(
        db,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
        action="LOGOUT",
        entity_type="auth_session",
        entity_id=current_context.session.id,
    )
    db.commit()
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    return None


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


@router.get(
    "/session",
    response_model=AuthSessionRead,
    response_model_exclude_none=True,
)
def current_session(current_context: CurrentAuthContext) -> AuthSessionRead:
    return AuthSessionRead.model_validate(current_context.session)


@router.post("/sessions/{session_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session_as_admin(
    session_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> None:
    auth_session = get_auth_session_for_tenant(
        db,
        session_id=session_id,
        organization_id=current_user.organization_id,
    )
    if auth_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authentication session not found",
        )

    changed = revoke_auth_session(
        auth_session=auth_session,
        revoked_by_id=current_user.id,
        reason="admin_revocation",
    )
    if changed:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="AUTH_SESSION_REVOKED",
            entity_type="auth_session",
            entity_id=auth_session.id,
            new_values={"target_user_id": str(auth_session.user_id)},
        )
        db.commit()
    return None


@router.get(
    "/identity-providers",
    response_model=list[EnterpriseIdentityProviderRead],
)
def identity_providers(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[EnterpriseIdentityProviderRead]:
    providers = list_identity_providers(
        db,
        organization_id=current_user.organization_id,
    )
    return [
        EnterpriseIdentityProviderRead.model_validate(provider)
        for provider in providers
    ]


@router.post(
    "/identity-providers",
    response_model=EnterpriseIdentityProviderRead,
    status_code=status.HTTP_201_CREATED,
)
def create_identity_provider_as_admin(
    payload: EnterpriseIdentityProviderCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> EnterpriseIdentityProviderRead:
    try:
        provider = create_identity_provider(
            db,
            organization_id=current_user.organization_id,
            provider_key=payload.provider_key,
            display_name=payload.display_name,
            protocol=payload.protocol,
            issuer_identifier=payload.issuer_identifier,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="ENTERPRISE_IDENTITY_PROVIDER_CREATED",
            entity_type="enterprise_identity_provider",
            entity_id=provider.id,
            new_values={
                "provider_key": provider.provider_key,
                "protocol": provider.protocol,
                "is_enabled": provider.is_enabled,
            },
        )
        db.commit()
        db.refresh(provider)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identity provider already exists",
        ) from exc
    return EnterpriseIdentityProviderRead.model_validate(provider)


def _set_provider_enabled(
    *,
    provider_id: UUID,
    enabled: bool,
    db: Session,
    current_user: User,
) -> EnterpriseIdentityProviderRead:
    provider = get_identity_provider_for_tenant(
        db,
        provider_id=provider_id,
        organization_id=current_user.organization_id,
    )
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity provider not found",
        )
    changed = set_identity_provider_enabled(provider=provider, enabled=enabled)
    if changed:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action=(
                "ENTERPRISE_IDENTITY_PROVIDER_ENABLED"
                if enabled
                else "ENTERPRISE_IDENTITY_PROVIDER_DISABLED"
            ),
            entity_type="enterprise_identity_provider",
            entity_id=provider.id,
            new_values={"is_enabled": provider.is_enabled},
        )
        db.commit()
        db.refresh(provider)
    return EnterpriseIdentityProviderRead.model_validate(provider)


@router.post(
    "/identity-providers/{provider_id}/enable",
    response_model=EnterpriseIdentityProviderRead,
)
def enable_identity_provider_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> EnterpriseIdentityProviderRead:
    return _set_provider_enabled(
        provider_id=provider_id,
        enabled=True,
        db=db,
        current_user=current_user,
    )


@router.post(
    "/identity-providers/{provider_id}/disable",
    response_model=EnterpriseIdentityProviderRead,
)
def disable_identity_provider_as_admin(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> EnterpriseIdentityProviderRead:
    return _set_provider_enabled(
        provider_id=provider_id,
        enabled=False,
        db=db,
        current_user=current_user,
    )


@router.get(
    "/identity-providers/{provider_id}/bindings",
    response_model=list[ExternalIdentityBindingRead],
)
def external_identity_bindings(
    provider_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[ExternalIdentityBindingRead]:
    provider = get_identity_provider_for_tenant(
        db,
        provider_id=provider_id,
        organization_id=current_user.organization_id,
    )
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity provider not found",
        )
    bindings = list_external_identity_bindings(
        db,
        provider_id=provider.id,
        organization_id=current_user.organization_id,
    )
    return [
        ExternalIdentityBindingRead.model_validate(binding)
        for binding in bindings
    ]


@router.post(
    "/identity-providers/{provider_id}/bindings",
    response_model=ExternalIdentityBindingRead,
    status_code=status.HTTP_201_CREATED,
)
def create_external_identity_binding_as_admin(
    provider_id: UUID,
    payload: ExternalIdentityBindingCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> ExternalIdentityBindingRead:
    provider = get_identity_provider_for_tenant(
        db,
        provider_id=provider_id,
        organization_id=current_user.organization_id,
    )
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity provider not found",
        )

    target_user = get_user_for_tenant(
        db,
        user_id=payload.user_id,
        organization_id=current_user.organization_id,
    )
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    try:
        binding = create_external_identity_binding(
            db,
            provider=provider,
            user=target_user,
            external_subject=payload.external_subject,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EXTERNAL_IDENTITY_BOUND",
            entity_type="external_identity_binding",
            entity_id=binding.id,
            new_values={
                "provider_id": str(provider.id),
                "target_user_id": str(target_user.id),
            },
        )
        db.commit()
        db.refresh(binding)
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
            detail="External identity binding conflicts with an existing binding",
        ) from exc

    return ExternalIdentityBindingRead.model_validate(binding)


@router.post(
    "/external-bindings/{binding_id}/revoke",
    response_model=ExternalIdentityBindingRead,
)
def revoke_external_identity_binding_as_admin(
    binding_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> ExternalIdentityBindingRead:
    binding = get_external_identity_binding_for_tenant(
        db,
        binding_id=binding_id,
        organization_id=current_user.organization_id,
    )
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External identity binding not found",
        )

    changed = revoke_external_identity_binding(
        binding=binding,
        revoked_by_id=current_user.id,
    )
    if changed:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EXTERNAL_IDENTITY_BINDING_REVOKED",
            entity_type="external_identity_binding",
            entity_id=binding.id,
            new_values={
                "provider_id": str(binding.provider_id),
                "target_user_id": str(binding.user_id),
            },
        )
        db.commit()
        db.refresh(binding)
    return ExternalIdentityBindingRead.model_validate(binding)

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.models import OidcAuthorizationTransaction
from app.modules.auth.oidc_callback import (
    OidcCallbackError,
    OidcProviderUnavailable,
    OidcRuntimeNotOperational,
    complete_oidc_callback,
)
from app.modules.auth.schemas import LoginResponse, OidcCallbackCompleteRequest
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()


def _audit_failed_callback(
    db: Session,
    *,
    transaction_id,
    failure_category: str,
) -> None:
    transaction = db.get(OidcAuthorizationTransaction, transaction_id)
    if transaction is None:
        return
    write_audit_log(
        db,
        organization_id=transaction.organization_id,
        user_id=None,
        action="OIDC_LOGIN_FAILED",
        entity_type="oidc_authorization_transaction",
        entity_id=transaction.id,
        new_values={"failure_category": failure_category},
    )
    db.commit()


@router.post("/oidc/callback", response_model=LoginResponse)
def complete_oidc_authorization_callback(
    payload: OidcCallbackCompleteRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    try:
        result = complete_oidc_callback(
            db,
            transaction_id=payload.transaction_id,
            state=payload.state,
            nonce=payload.nonce,
            code_verifier=payload.code_verifier,
            authorization_code=payload.authorization_code,
        )
        db.commit()
        db.refresh(result.user)
        db.refresh(result.auth_session)
    except OidcProviderUnavailable as exc:
        db.rollback()
        _audit_failed_callback(
            db,
            transaction_id=payload.transaction_id,
            failure_category="provider_unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OIDC identity provider is temporarily unavailable",
        ) from exc
    except OidcRuntimeNotOperational as exc:
        db.rollback()
        _audit_failed_callback(
            db,
            transaction_id=payload.transaction_id,
            failure_category="runtime_not_operational",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OIDC provider runtime is not operational for this flow",
        ) from exc
    except (OidcCallbackError, ValueError) as exc:
        db.rollback()
        _audit_failed_callback(
            db,
            transaction_id=payload.transaction_id,
            failure_category="identity_verification_failed",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OIDC authentication failed",
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        _audit_failed_callback(
            db,
            transaction_id=payload.transaction_id,
            failure_category="authority_conflict",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OIDC authentication transaction has already been finalized",
        ) from exc

    token = create_access_token(
        user_id=result.user.id,
        organization_id=result.user.organization_id,
        role=result.user.role.value,
        session_id=result.auth_session.id,
        identity_source=result.auth_session.identity_source,
        auth_method=result.auth_session.auth_method,
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
    return LoginResponse(
        access_token=token,
        user=UserRead.model_validate(result.user),
    )

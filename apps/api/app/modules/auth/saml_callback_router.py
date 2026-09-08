from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.saml_assurance_evidence import (
    apply_saml_mfa_assurance_after_verified_callback,
)
from app.modules.auth.saml_callback import SamlCallbackError, complete_saml_callback
from app.modules.auth.saml_transaction import validate_saml_relay_state_source
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()


def _audit_failed_callback(
    db: Session,
    *,
    relay_state: str,
    failure_category: str,
) -> None:
    try:
        transaction, _ = validate_saml_relay_state_source(
            db,
            relay_state=relay_state,
        )
    except ValueError:
        return
    write_audit_log(
        db,
        organization_id=transaction.organization_id,
        user_id=None,
        action="SAML_LOGIN_FAILED",
        entity_type="saml_authn_transaction",
        entity_id=transaction.id,
        new_values={"failure_category": failure_category},
    )
    db.commit()


@router.post("/saml/callback", response_model=UserRead)
def complete_saml_authorization_callback(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    relay_state: Annotated[
        str,
        Form(alias="RelayState", min_length=50, max_length=80),
    ],
    saml_response: Annotated[
        str,
        Form(alias="SAMLResponse", min_length=1, max_length=1_500_000),
    ],
) -> UserRead:
    try:
        result = complete_saml_callback(
            db,
            relay_state=relay_state,
            saml_response=saml_response,
        )
        apply_saml_mfa_assurance_after_verified_callback(
            db,
            transaction=result.transaction,
            auth_session=result.auth_session,
            saml_response=saml_response,
            user_id=result.user.id,
        )
        db.commit()
        db.refresh(result.user)
        db.refresh(result.auth_session)
    except (SamlCallbackError, ValueError) as exc:
        db.rollback()
        _audit_failed_callback(
            db,
            relay_state=relay_state,
            failure_category="identity_verification_failed",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SAML authentication failed",
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        _audit_failed_callback(
            db,
            relay_state=relay_state,
            failure_category="authority_conflict",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SAML authentication transaction has already been finalized",
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
    return UserRead.model_validate(result.user)

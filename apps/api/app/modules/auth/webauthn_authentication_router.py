from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentAuthContext
from app.modules.auth.webauthn_authentication import (
    WEBAUTHN_AUTHENTICATION_TIMEOUT_MS,
    begin_webauthn_authentication,
    cancel_webauthn_authentication,
    finish_webauthn_authentication,
)
from app.modules.auth.webauthn_registration_finish import WebAuthnVerificationError
from app.modules.auth.webauthn_schemas import (
    WebAuthnAuthenticationBeginResponse,
    WebAuthnAuthenticationFinishRequest,
    WebAuthnAuthenticationTransactionRead,
    WebAuthnAuthenticationVerifiedResponse,
)

router = APIRouter(
    prefix="/auth/webauthn/authentication",
    tags=["authentication", "mfa", "webauthn"],
)


@router.post(
    "/begin",
    response_model=WebAuthnAuthenticationBeginResponse,
    status_code=status.HTTP_201_CREATED,
)
def begin_current_webauthn_authentication(
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> WebAuthnAuthenticationBeginResponse:
    try:
        transaction, challenge, profile, superseded_id = begin_webauthn_authentication(
            db,
            user=current_context.user,
            auth_session=current_context.session,
        )
        if superseded_id is not None:
            write_audit_log(
                db,
                organization_id=current_context.user.organization_id,
                user_id=current_context.user.id,
                action="WEBAUTHN_AUTHENTICATION_SUPERSEDED",
                entity_type="webauthn_authentication_transaction",
                entity_id=superseded_id,
                new_values={"auth_session_id": str(current_context.session.id)},
            )
        write_audit_log(
            db,
            organization_id=current_context.user.organization_id,
            user_id=current_context.user.id,
            action="WEBAUTHN_AUTHENTICATION_BEGUN",
            entity_type="webauthn_authentication_transaction",
            entity_id=transaction.id,
            new_values={
                "auth_session_id": str(current_context.session.id),
                "profile_id": str(profile.id),
                "profile_number": profile.profile_number,
                "profile_hash": profile.profile_hash,
            },
        )
        db.commit()
        db.refresh(transaction)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WebAuthn authentication transaction conflicts with current session custody",
        ) from exc

    return WebAuthnAuthenticationBeginResponse(
        transaction_id=transaction.id,
        challenge=challenge,
        expires_at=transaction.expires_at,
        timeout_ms=WEBAUTHN_AUTHENTICATION_TIMEOUT_MS,
        rp_id=profile.rp_id,
        user_verification="required",
    )


@router.post(
    "/{transaction_id}/finish",
    response_model=WebAuthnAuthenticationVerifiedResponse,
)
def finish_current_webauthn_authentication(
    transaction_id: UUID,
    payload: WebAuthnAuthenticationFinishRequest,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> WebAuthnAuthenticationVerifiedResponse:
    try:
        auth_session, transaction, credential = finish_webauthn_authentication(
            db,
            transaction_id=transaction_id,
            user=current_context.user,
            auth_session=current_context.session,
            credential_id=payload.credential_id,
            client_data_json=payload.client_data_json,
            authenticator_data=payload.authenticator_data,
            signature=payload.signature,
        )
        write_audit_log(
            db,
            organization_id=current_context.user.organization_id,
            user_id=current_context.user.id,
            action="WEBAUTHN_MFA_SESSION_VERIFIED",
            entity_type="auth_session",
            entity_id=auth_session.id,
            new_values={
                "mfa_method": "webauthn",
                "authentication_transaction_id": str(transaction.id),
                "webauthn_credential_id": str(credential.id),
                "profile_id": str(transaction.profile_id),
                "profile_number": transaction.profile_number,
                "sign_count": credential.sign_count,
            },
        )
        db.commit()
        db.refresh(auth_session)
        db.refresh(transaction)
        db.refresh(credential)
    except WebAuthnVerificationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WebAuthn authentication assertion conflicts with current custody",
        ) from exc

    if auth_session.mfa_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WebAuthn MFA verification state was not recorded",
        )
    return WebAuthnAuthenticationVerifiedResponse(
        auth_session_id=auth_session.id,
        mfa_verified_at=auth_session.mfa_verified_at,
        mfa_method="webauthn",
        authentication_transaction_id=transaction.id,
        credential_id=credential.id,
        sign_count=credential.sign_count,
    )


@router.post(
    "/{transaction_id}/cancel",
    response_model=WebAuthnAuthenticationTransactionRead,
)
def cancel_current_webauthn_authentication(
    transaction_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> WebAuthnAuthenticationTransactionRead:
    try:
        transaction = cancel_webauthn_authentication(
            db,
            transaction_id=transaction_id,
            user=current_context.user,
            auth_session=current_context.session,
        )
        write_audit_log(
            db,
            organization_id=current_context.user.organization_id,
            user_id=current_context.user.id,
            action="WEBAUTHN_AUTHENTICATION_CANCELLED",
            entity_type="webauthn_authentication_transaction",
            entity_id=transaction.id,
            new_values={
                "auth_session_id": str(current_context.session.id),
                "profile_id": str(transaction.profile_id),
                "profile_number": transaction.profile_number,
            },
        )
        db.commit()
        db.refresh(transaction)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return WebAuthnAuthenticationTransactionRead.model_validate(transaction)

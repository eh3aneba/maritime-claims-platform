from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentAuthContext, enforce_mfa_policy_for_context
from app.modules.auth.webauthn_registration import (
    WEBAUTHN_REGISTRATION_TIMEOUT_MS,
    begin_webauthn_registration,
    cancel_webauthn_registration,
)
from app.modules.auth.webauthn_schemas import (
    WebAuthnAuthenticatorSelection,
    WebAuthnCredentialParameter,
    WebAuthnRegistrationBeginResponse,
    WebAuthnRegistrationRp,
    WebAuthnRegistrationTransactionRead,
    WebAuthnRegistrationUser,
)

router = APIRouter(prefix="/auth/webauthn/registration", tags=["authentication", "mfa", "webauthn"])


@router.post(
    "/begin",
    response_model=WebAuthnRegistrationBeginResponse,
    status_code=status.HTTP_201_CREATED,
)
def begin_current_webauthn_registration(
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> WebAuthnRegistrationBeginResponse:
    enforce_mfa_policy_for_context(db, context=current_context)
    try:
        transaction, material, profile, superseded_id = begin_webauthn_registration(
            db,
            user=current_context.user,
            auth_session=current_context.session,
        )
        if superseded_id is not None:
            write_audit_log(
                db,
                organization_id=current_context.user.organization_id,
                user_id=current_context.user.id,
                action="WEBAUTHN_REGISTRATION_SUPERSEDED",
                entity_type="webauthn_registration_transaction",
                entity_id=superseded_id,
                new_values={"auth_session_id": str(current_context.session.id)},
            )
        write_audit_log(
            db,
            organization_id=current_context.user.organization_id,
            user_id=current_context.user.id,
            action="WEBAUTHN_REGISTRATION_BEGUN",
            entity_type="webauthn_registration_transaction",
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
            detail="WebAuthn registration transaction conflicts with current session custody",
        ) from exc

    return WebAuthnRegistrationBeginResponse(
        transaction_id=transaction.id,
        challenge=material.challenge,
        expires_at=transaction.expires_at,
        timeout_ms=WEBAUTHN_REGISTRATION_TIMEOUT_MS,
        rp=WebAuthnRegistrationRp(id=profile.rp_id, name=profile.rp_name),
        user=WebAuthnRegistrationUser(
            id=material.user_handle,
            name=current_context.user.email,
            display_name=current_context.user.full_name,
        ),
        pub_key_cred_params=[
            WebAuthnCredentialParameter(alg=-7),
            WebAuthnCredentialParameter(alg=-257),
        ],
        authenticator_selection=WebAuthnAuthenticatorSelection(),
        attestation="none",
    )


@router.post(
    "/{transaction_id}/cancel",
    response_model=WebAuthnRegistrationTransactionRead,
)
def cancel_current_webauthn_registration(
    transaction_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> WebAuthnRegistrationTransactionRead:
    enforce_mfa_policy_for_context(db, context=current_context)
    try:
        transaction = cancel_webauthn_registration(
            db,
            transaction_id=transaction_id,
            user=current_context.user,
            auth_session=current_context.session,
        )
        write_audit_log(
            db,
            organization_id=current_context.user.organization_id,
            user_id=current_context.user.id,
            action="WEBAUTHN_REGISTRATION_CANCELLED",
            entity_type="webauthn_registration_transaction",
            entity_id=transaction.id,
            new_values={
                "auth_session_id": str(current_context.session.id),
                "profile_id": str(transaction.profile_id),
                "profile_number": transaction.profile_number,
                "profile_hash": transaction.profile_hash,
            },
        )
        db.commit()
        db.refresh(transaction)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return WebAuthnRegistrationTransactionRead.model_validate(transaction)

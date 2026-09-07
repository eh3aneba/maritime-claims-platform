from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.oidc_transaction import create_oidc_authorization_transaction
from app.modules.auth.schemas import (
    OidcAuthorizationTransactionCreate,
    OidcAuthorizationTransactionStartResponse,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/oidc/transactions",
    response_model=OidcAuthorizationTransactionStartResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_oidc_authorization_transaction(
    payload: OidcAuthorizationTransactionCreate,
    db: Annotated[Session, Depends(get_db)],
) -> OidcAuthorizationTransactionStartResponse:
    try:
        (
            transaction,
            material,
            provider,
            trust_profile,
            runtime_profile,
        ) = create_oidc_authorization_transaction(
            db,
            organization_slug=payload.organization_slug,
            provider_key=payload.provider_key,
        )
        write_audit_log(
            db,
            organization_id=transaction.organization_id,
            user_id=None,
            action="OIDC_AUTHORIZATION_TRANSACTION_CREATED",
            entity_type="oidc_authorization_transaction",
            entity_id=transaction.id,
            new_values={
                "provider_id": str(provider.id),
                "trust_profile_id": str(trust_profile.id),
                "trust_profile_number": trust_profile.profile_number,
                "trust_profile_hash": trust_profile.profile_hash,
                "runtime_profile_id": str(runtime_profile.id),
                "runtime_profile_number": runtime_profile.runtime_profile_number,
                "runtime_profile_hash": runtime_profile.runtime_profile_hash,
                "pkce_method": transaction.pkce_method,
                "expires_at": transaction.expires_at.isoformat(),
            },
        )
        db.commit()
        db.refresh(transaction)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OIDC provider is unavailable",
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OIDC authorization transaction could not be created",
        ) from exc

    return OidcAuthorizationTransactionStartResponse(
        transaction_id=transaction.id,
        provider_key=provider.provider_key,
        provider_display_name=provider.display_name,
        issuer_identifier=trust_profile.issuer_identifier,
        audience=trust_profile.audience,
        trust_profile_id=trust_profile.id,
        trust_profile_number=trust_profile.profile_number,
        trust_profile_hash=trust_profile.profile_hash,
        runtime_profile_id=runtime_profile.id,
        runtime_profile_number=runtime_profile.runtime_profile_number,
        runtime_profile_hash=runtime_profile.runtime_profile_hash,
        authorization_endpoint=runtime_profile.authorization_endpoint,
        token_endpoint=runtime_profile.token_endpoint,
        redirect_uri=runtime_profile.redirect_uri,
        scopes=list(runtime_profile.scopes),
        client_auth_method=runtime_profile.client_auth_method,
        state=material.state,
        nonce=material.nonce,
        code_verifier=material.code_verifier,
        code_challenge=material.code_challenge,
        expires_at=transaction.expires_at,
    )

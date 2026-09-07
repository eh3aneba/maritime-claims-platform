from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.saml_callback import SamlCallbackError, build_saml_authorization_url
from app.modules.auth.saml_transaction import create_saml_authn_transaction
from app.modules.auth.schemas import (
    SamlAuthnTransactionCreate,
    SamlAuthnTransactionStartResponse,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/saml/transactions",
    response_model=SamlAuthnTransactionStartResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_saml_authn_transaction(
    payload: SamlAuthnTransactionCreate,
    db: Annotated[Session, Depends(get_db)],
) -> SamlAuthnTransactionStartResponse:
    try:
        transaction, material, provider, profile = create_saml_authn_transaction(
            db,
            organization_slug=payload.organization_slug,
            provider_key=payload.provider_key,
        )
        authorization_url = build_saml_authorization_url(
            profile=profile,
            material=material,
        )
        write_audit_log(
            db,
            organization_id=transaction.organization_id,
            user_id=None,
            action="SAML_AUTHN_TRANSACTION_CREATED",
            entity_type="saml_authn_transaction",
            entity_id=transaction.id,
            new_values={
                "provider_id": str(provider.id),
                "profile_id": str(profile.id),
                "profile_number": profile.profile_number,
                "profile_hash": profile.profile_hash,
                "authn_request_binding": profile.authn_request_binding,
                "response_binding": profile.response_binding,
                "expires_at": transaction.expires_at.isoformat(),
            },
        )
        db.commit()
        db.refresh(transaction)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SAML provider is unavailable",
        ) from exc
    except SamlCallbackError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SAML provider runtime is not operational for this flow",
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SAML authentication transaction could not be created",
        ) from exc

    return SamlAuthnTransactionStartResponse(
        transaction_id=transaction.id,
        provider_key=provider.provider_key,
        provider_display_name=provider.display_name,
        idp_entity_identifier=profile.idp_entity_identifier,
        profile_id=profile.id,
        profile_number=profile.profile_number,
        profile_hash=profile.profile_hash,
        idp_sso_url=profile.idp_sso_url,
        sp_entity_id=profile.sp_entity_id,
        acs_url=profile.acs_url,
        authorization_url=authorization_url,
        request_id=material.request_id,
        relay_state=material.relay_state,
        expires_at=transaction.expires_at,
    )

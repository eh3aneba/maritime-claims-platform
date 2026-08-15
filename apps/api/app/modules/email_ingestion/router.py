from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.email_ingestion.schemas import (
    EmailConnectionCreate, EmailConnectionResponse, EmailConnectionTransition, EmailInboxResponse,
    EmailReview, ExpiryResponse, IngestedEmailResponse, NormalizedEmailInput,
)
from app.modules.email_ingestion.service import (
    create_connection, expire_due, get_connection, get_message, ingest_email, list_inbox,
    message_response, review_email, transition_connection,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/email-ingestion", tags=["email-ingestion"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]


@router.get("/inbox", response_model=EmailInboxResponse)
def inbox(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    connections, messages = list_inbox(db, current_user.organization_id)
    return EmailInboxResponse(connections=connections, messages=messages)


@router.post("/connections", response_model=EmailConnectionResponse, status_code=201)
def connection_create(payload: EmailConnectionCreate, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    item, token = create_connection(db, manager, payload)
    return EmailConnectionResponse.model_validate(item).model_copy(update={"ingestion_token": token})


@router.post("/connections/{connection_id}/transition", response_model=EmailConnectionResponse)
def connection_transition(connection_id: UUID, payload: EmailConnectionTransition, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return transition_connection(db, get_connection(db, manager.organization_id, connection_id), manager, payload.action, payload.note)


@router.post("/webhooks/{connection_id}", response_model=IngestedEmailResponse, status_code=201)
def webhook(connection_id: UUID, payload: NormalizedEmailInput,
            db: Annotated[Session, Depends(get_db)],
            token: Annotated[str | None, Header(alias="X-MCRI-Ingestion-Token")] = None):
    item = ingest_email(db, connection_id, token, payload)
    return IngestedEmailResponse(**message_response(db, item))


@router.post("/messages/{message_id}/review", response_model=IngestedEmailResponse)
def message_review(message_id: UUID, payload: EmailReview, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    item = review_email(db, get_message(db, current_user.organization_id, message_id), current_user, payload)
    return IngestedEmailResponse(**message_response(db, item))


@router.post("/expire-due", response_model=ExpiryResponse)
def expiry(manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return ExpiryResponse(expired_count=expire_due(db, manager))

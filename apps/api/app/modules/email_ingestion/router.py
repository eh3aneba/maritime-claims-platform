from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.email_ingestion.schemas import (
    EmailAdapterCreate, EmailAdapterOperations, EmailAdapterResponse, EmailAdapterRunCreate,
    EmailAdapterRunResponse, EmailConnectionCreate, EmailConnectionResponse,
    EmailConnectionTransition, EmailInboxResponse, EmailReview, ExpiryResponse,
    IngestedEmailResponse, NormalizedEmailInput, RetentionRunCreate, RetentionRunResponse,
)
from app.modules.email_ingestion.service import (
    create_adapter, create_connection, expire_due, get_adapter, get_connection, get_message,
    ingest_email, list_adapter_operations, list_inbox, message_response, record_adapter_run,
    review_email, run_retention, transition_adapter, transition_connection,
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


@router.get("/adapter-operations", response_model=EmailAdapterOperations)
def adapter_operations(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    adapters, runs, retention_runs = list_adapter_operations(db, current_user.organization_id)
    return EmailAdapterOperations(adapters=adapters, runs=runs, retention_runs=retention_runs)


@router.post("/adapters", response_model=EmailAdapterResponse, status_code=201)
def adapter_create(payload: EmailAdapterCreate, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return create_adapter(db, manager, payload)


@router.post("/adapters/{adapter_id}/transition", response_model=EmailAdapterResponse)
def adapter_transition(adapter_id: UUID, payload: EmailConnectionTransition, manager: Manager,
                       db: Annotated[Session, Depends(get_db)]):
    return transition_adapter(db, get_adapter(db, manager.organization_id, adapter_id), manager,
                              payload.action, payload.note)


@router.post("/adapters/{adapter_id}/runs", response_model=EmailAdapterRunResponse, status_code=201)
def adapter_run(adapter_id: UUID, payload: EmailAdapterRunCreate, manager: Manager,
                db: Annotated[Session, Depends(get_db)]):
    return record_adapter_run(db, get_adapter(db, manager.organization_id, adapter_id), manager, payload)


@router.post("/retention-runs", response_model=RetentionRunResponse, status_code=201)
def retention_run(payload: RetentionRunCreate, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return run_retention(db, manager, payload.idempotency_key)

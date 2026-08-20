from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.ai_governance.schemas import (
    AIDocumentEligibilityCreate, AIDocumentEligibilityResponse,
    AIDocumentEligibilityRevoke, AIGovernanceDashboard,
    AIProviderActivationApprovalWrite, AIProviderActivationCreate,
    AIProviderActivationDecision, AIProviderActivationResponse,
    AIProviderActivationRevoke,
)
from app.modules.ai_governance.service import (
    attest_document_eligibility, create_activation_request,
    decide_activation_request, get_activation_request, get_document_eligibility,
    list_activation_requests, list_document_eligibility, record_activation_approval,
    revoke_activation_request, revoke_document_eligibility,
)
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/ai-governance", tags=["ai-governance"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=AIGovernanceDashboard)
def ai_governance_dashboard(current_user: CurrentUser,
                            db: Annotated[Session, Depends(get_db)]):
    return AIGovernanceDashboard(
        activation_requests=list_activation_requests(db, current_user.organization_id),
        document_eligibility=list_document_eligibility(db, current_user.organization_id),
    )


@router.post("/activations", response_model=AIProviderActivationResponse, status_code=201)
def activation_create(payload: AIProviderActivationCreate, manager: Manager,
                      db: Annotated[Session, Depends(get_db)]):
    return create_activation_request(db, manager, payload)


@router.post("/activations/{item_id}/approvals",
             response_model=AIProviderActivationResponse)
def activation_approval(item_id: UUID, payload: AIProviderActivationApprovalWrite,
                        manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return record_activation_approval(
        db, manager, get_activation_request(db, manager.organization_id, item_id),
        payload.approval_role, payload.action, payload.evidence_reference, payload.note)


@router.post("/activations/{item_id}/decision",
             response_model=AIProviderActivationResponse)
def activation_decision(item_id: UUID, payload: AIProviderActivationDecision,
                        admin: Admin, db: Annotated[Session, Depends(get_db)]):
    return decide_activation_request(
        db, admin, get_activation_request(db, admin.organization_id, item_id),
        payload.outcome, payload.confirm_decision, payload.note)


@router.post("/activations/{item_id}/revoke",
             response_model=AIProviderActivationResponse)
def activation_revoke(item_id: UUID, payload: AIProviderActivationRevoke,
                      manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return revoke_activation_request(
        db, manager, get_activation_request(db, manager.organization_id, item_id),
        payload.confirm_revoke, payload.note)


@router.post("/document-eligibility", response_model=AIDocumentEligibilityResponse,
             status_code=201)
def document_eligibility_create(payload: AIDocumentEligibilityCreate, manager: Manager,
                                db: Annotated[Session, Depends(get_db)]):
    return attest_document_eligibility(db, manager, payload)


@router.post("/document-eligibility/{item_id}/revoke",
             response_model=AIDocumentEligibilityResponse)
def document_eligibility_revoke(item_id: UUID, payload: AIDocumentEligibilityRevoke,
                                manager: Manager,
                                db: Annotated[Session, Depends(get_db)]):
    return revoke_document_eligibility(
        db, manager, get_document_eligibility(db, manager.organization_id, item_id),
        payload.confirm_revoke, payload.note)

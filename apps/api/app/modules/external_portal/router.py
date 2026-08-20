from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.external_portal.schemas import (
    PortalAccept, PortalInvitationCreate, PortalInvitationResponse, PortalReview, PortalRevoke,
    PortalSessionResponse, PortalSubmissionCreate, PortalSubmissionResponse, PortalView, PortalWorkspace,
    PublicationProposalCreate, PublicationProposalResponse, PublicationReview,
)
from app.modules.external_portal.service import (
    accept_invitation, authenticate_session, create_invitation, create_submission, get_invitation,
    create_publication_proposal, get_publication_proposal, get_submission, invitation_response,
    list_workspace, portal_view, review_publication_proposal, review_submission, revoke_invitation,
)
from app.modules.users.models import User, UserRole

router = APIRouter(tags=["external-portal"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]


@router.get("/claims/{claim_id}/external-portal", response_model=PortalWorkspace)
def workspace(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    invitations, submissions, proposals = list_workspace(db, current_user.organization_id, claim_id)
    return PortalWorkspace(invitations=invitations, submissions=submissions, publication_proposals=proposals)


@router.post("/claims/{claim_id}/external-portal/invitations", response_model=PortalInvitationResponse, status_code=201)
def invitation_create(claim_id: UUID, payload: PortalInvitationCreate, manager: Manager,
                      db: Annotated[Session, Depends(get_db)]):
    item, token = create_invitation(db, manager, claim_id, payload)
    return PortalInvitationResponse(**invitation_response(db, item, token))


@router.post("/claims/{claim_id}/external-portal/invitations/{invitation_id}/revoke", response_model=PortalInvitationResponse)
def invitation_revoke(claim_id: UUID, invitation_id: UUID, payload: PortalRevoke, manager: Manager,
                      db: Annotated[Session, Depends(get_db)]):
    item = get_invitation(db, manager.organization_id, invitation_id)
    if item.claim_id != claim_id:
        raise HTTPException(404, "Portal invitation not found")
    return PortalInvitationResponse(**invitation_response(db, revoke_invitation(db, item, manager, payload.note)))


@router.post("/claims/{claim_id}/external-portal/invitations/{invitation_id}/publications", response_model=PublicationProposalResponse, status_code=201)
def publication_propose(claim_id: UUID, invitation_id: UUID, payload: PublicationProposalCreate,
                        current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    item = get_invitation(db, current_user.organization_id, invitation_id)
    if item.claim_id != claim_id: raise HTTPException(404, "Portal invitation not found")
    return create_publication_proposal(db, current_user, item, payload)


@router.post("/claims/{claim_id}/external-portal/publications/{proposal_id}/review", response_model=PublicationProposalResponse)
def publication_review(claim_id: UUID, proposal_id: UUID, payload: PublicationReview, manager: Manager,
                       db: Annotated[Session, Depends(get_db)]):
    item = get_publication_proposal(db, manager.organization_id, proposal_id)
    invitation = get_invitation(db, manager.organization_id, item.invitation_id)
    if invitation.claim_id != claim_id: raise HTTPException(404, "Publication proposal not found")
    return review_publication_proposal(db, manager, item, payload.action, payload.note)


@router.post("/claims/{claim_id}/external-portal/submissions/{submission_id}/review", response_model=PortalSubmissionResponse)
def submission_review(claim_id: UUID, submission_id: UUID, payload: PortalReview, current_user: CurrentUser,
                      db: Annotated[Session, Depends(get_db)]):
    item = get_submission(db, current_user.organization_id, submission_id)
    if item.claim_id != claim_id:
        raise HTTPException(404, "Portal submission not found")
    return review_submission(db, item, current_user, payload)


@router.post("/external-portal/accept", response_model=PortalSessionResponse)
def portal_accept(payload: PortalAccept, db: Annotated[Session, Depends(get_db)]):
    token, expires = accept_invitation(db, payload.invitation_token)
    return PortalSessionResponse(session_token=token, expires_at=expires)


@router.get("/external-portal/session", response_model=PortalView)
def session_view(db: Annotated[Session, Depends(get_db)],
                 token: Annotated[str | None, Header(alias="X-MCRI-Portal-Session")] = None):
    _, invitation = authenticate_session(db, token)
    return PortalView(**portal_view(db, invitation))


@router.post("/external-portal/submissions", response_model=PortalSubmissionResponse, status_code=201)
def portal_submission(payload: PortalSubmissionCreate, db: Annotated[Session, Depends(get_db)],
                      token: Annotated[str | None, Header(alias="X-MCRI-Portal-Session")] = None):
    _, invitation = authenticate_session(db, token)
    return create_submission(db, invitation, payload)

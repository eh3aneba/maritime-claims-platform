import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.correspondence.models import (
    ClaimCorrespondence, CorrespondenceChannel, CorrespondenceDirection, CorrespondenceKind,
    CorrespondenceSensitivity, CorrespondenceStatus,
)
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentMalwareScanStatus
from app.modules.external_portal.models import (
    ExternalPortalInvitation, ExternalPortalPublicationProposal, ExternalPortalPublishedItem,
    ExternalPortalSession, ExternalPortalSubmission,
)
from app.modules.external_portal.schemas import (
    PortalInvitationCreate, PortalReview, PortalSubmissionCreate, PublicationProposalCreate,
)
from app.modules.users.models import User
from app.modules.vessels.models import Vessel

PORTAL_PERMISSIONS = {"claim_summary.view", "published_items.view", "submission.create"}


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _audit(db: Session, *, org: UUID, user: UUID | None, action: str, kind: str,
           entity: UUID, values: dict, details: str) -> None:
    write_audit_log(db, organization_id=org, user_id=user, action=action, entity_type=kind,
                    entity_id=entity, new_values=values, details=details)


def get_claim(db: Session, organization_id: UUID, claim_id: UUID) -> Claim:
    claim = db.scalar(select(Claim).where(Claim.id == claim_id, Claim.organization_id == organization_id))
    if claim is None:
        raise HTTPException(404, "Claim not found")
    return claim


def _published(db: Session, invitation_id: UUID):
    return list(db.scalars(select(ExternalPortalPublishedItem).where(
        ExternalPortalPublishedItem.invitation_id == invitation_id,
    ).order_by(ExternalPortalPublishedItem.created_at.asc())))


def invitation_response(db: Session, item: ExternalPortalInvitation, token: str | None = None) -> dict:
    data = {column.name: getattr(item, column.name) for column in item.__table__.columns
            if column.name not in {"organization_id", "created_by_id", "token_hash", "updated_at"}}
    return {**data, "invitation_token": token, "published_items": _published(db, item.id)}


def list_workspace(db: Session, organization_id: UUID, claim_id: UUID):
    get_claim(db, organization_id, claim_id)
    invitations = list(db.scalars(select(ExternalPortalInvitation).where(
        ExternalPortalInvitation.organization_id == organization_id,
        ExternalPortalInvitation.claim_id == claim_id,
    ).order_by(ExternalPortalInvitation.created_at.desc())))
    submissions = list(db.scalars(select(ExternalPortalSubmission).where(
        ExternalPortalSubmission.organization_id == organization_id,
        ExternalPortalSubmission.claim_id == claim_id,
    ).order_by(ExternalPortalSubmission.submitted_at.desc())))
    proposals = list(db.scalars(select(ExternalPortalPublicationProposal).where(
        ExternalPortalPublicationProposal.organization_id == organization_id,
        ExternalPortalPublicationProposal.invitation_id.in_([item.id for item in invitations]),
    ).order_by(ExternalPortalPublicationProposal.created_at.desc()))) if invitations else []
    return [invitation_response(db, item) for item in invitations], submissions, proposals


def _validate_published_item(db: Session, claim: Claim, item) -> None:
    if item.item_type == "correspondence":
        source = db.scalar(select(ClaimCorrespondence).where(
            ClaimCorrespondence.id == item.source_id,
            ClaimCorrespondence.organization_id == claim.organization_id,
            ClaimCorrespondence.claim_id == claim.id,
        ))
        allowed_statuses = {CorrespondenceStatus.APPROVED, CorrespondenceStatus.SENT_EXTERNALLY,
                            CorrespondenceStatus.RECEIVED_EXTERNAL}
        if source is None or source.sensitivity != CorrespondenceSensitivity.STANDARD or source.status not in allowed_statuses:
            raise HTTPException(422, "Only standard reviewed correspondence may be published")
    else:
        source = db.scalar(select(Document).where(
            Document.id == item.source_id, Document.organization_id == claim.organization_id,
            Document.claim_id == claim.id, Document.deleted_at.is_(None), Document.is_current.is_(True),
        ))
        if (source is None or source.malware_scan_status != DocumentMalwareScanStatus.CLEAN
                or source.confidentiality_level == ConfidentialityLevel.RESTRICTED):
            raise HTTPException(422, "Only current malware-clean non-restricted document metadata may be published")


def create_invitation(db: Session, user: User, claim_id: UUID,
                      payload: PortalInvitationCreate) -> tuple[ExternalPortalInvitation, str]:
    claim = get_claim(db, user.organization_id, claim_id)
    permissions = set(payload.permission_manifest)
    if not permissions or not permissions.issubset(PORTAL_PERMISSIONS):
        raise HTTPException(422, "Portal permissions exceed the claim-scoped allowlist")
    if payload.published_items:
        raise HTTPException(422, "Direct publication is disabled; create a four-eyes publication proposal after invitation creation")
    token = secrets.token_urlsafe(32); now = datetime.now(UTC)
    item = ExternalPortalInvitation(
        organization_id=user.organization_id, claim_id=claim.id, created_by_id=user.id,
        participant_name=payload.participant_name.strip(), participant_email=str(payload.participant_email).lower(),
        purpose=payload.purpose.strip(), permission_manifest=sorted(permissions), status="pending",
        token_hash=sha256(token.encode()).hexdigest(), expires_at=now + timedelta(hours=payload.expires_in_hours),
    )
    db.add(item); db.flush()
    _audit(db, org=item.organization_id, user=user.id, action="CREATE_EXTERNAL_PORTAL_INVITATION",
           kind="external_portal_invitation", entity=item.id,
           values={"claim_id": str(claim.id), "participant_email": item.participant_email,
                   "permissions": item.permission_manifest, "published_count": 0,
                   "expires_at": item.expires_at.isoformat()},
           details="Invitation token displayed once; only its SHA-256 hash is stored.")
    db.commit(); db.refresh(item)
    return item, token


def create_publication_proposal(db: Session, user: User, invitation: ExternalPortalInvitation,
                                payload: PublicationProposalCreate) -> ExternalPortalPublicationProposal:
    if invitation.status in {"revoked", "expired"}:
        raise HTTPException(409, "Publication cannot be proposed for an unavailable invitation")
    claim = get_claim(db, user.organization_id, invitation.claim_id)
    _validate_published_item(db, claim, payload)
    item = ExternalPortalPublicationProposal(
        organization_id=user.organization_id, invitation_id=invitation.id, created_by_id=user.id,
        item_type=payload.item_type, source_id=payload.source_id, title=payload.title.strip(),
        summary=payload.summary.strip() if payload.summary else None, status="under_review",
    )
    db.add(item)
    try: db.flush()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "This source already has a publication proposal") from exc
    _audit(db, org=item.organization_id, user=user.id, action="PROPOSE_EXTERNAL_PORTAL_PUBLICATION",
           kind="external_portal_publication_proposal", entity=item.id,
           values={"invitation_id": str(invitation.id), "item_type": item.item_type, "source_id": str(item.source_id)},
           details="Publication requires approval by a different Manager/Admin.")
    db.commit(); db.refresh(item); return item


def get_publication_proposal(db: Session, org: UUID, proposal_id: UUID) -> ExternalPortalPublicationProposal:
    item = db.scalar(select(ExternalPortalPublicationProposal).where(
        ExternalPortalPublicationProposal.id == proposal_id,
        ExternalPortalPublicationProposal.organization_id == org,
    ))
    if item is None: raise HTTPException(404, "Publication proposal not found")
    return item


def review_publication_proposal(db: Session, user: User, item: ExternalPortalPublicationProposal,
                                action: str, note: str) -> ExternalPortalPublicationProposal:
    if item.status != "under_review": raise HTTPException(409, "Only pending publication proposals can be reviewed")
    if item.created_by_id == user.id: raise HTTPException(409, "The proposal creator cannot approve or reject it")
    invitation = get_invitation(db, user.organization_id, item.invitation_id)
    if invitation.status in {"revoked", "expired"}: raise HTTPException(409, "Invitation is unavailable")
    item.reviewed_by_id = user.id; item.review_note = note.strip(); item.reviewed_at = datetime.now(UTC)
    if action == "approve":
        claim = get_claim(db, user.organization_id, invitation.claim_id)
        _validate_published_item(db, claim, item)
        published = ExternalPortalPublishedItem(
            organization_id=user.organization_id, invitation_id=invitation.id, published_by_id=user.id,
            item_type=item.item_type, source_id=item.source_id, title=item.title, summary=item.summary,
        )
        db.add(published); db.flush(); item.published_item_id = published.id; item.status = "approved"
    elif action == "reject": item.status = "rejected"
    else: raise HTTPException(422, "Action must be approve or reject")
    _audit(db, org=item.organization_id, user=user.id,
           action="APPROVE_EXTERNAL_PORTAL_PUBLICATION" if item.status == "approved" else "REJECT_EXTERNAL_PORTAL_PUBLICATION",
           kind="external_portal_publication_proposal", entity=item.id,
           values={"status": item.status, "published_item_id": str(item.published_item_id) if item.published_item_id else None},
           details=note.strip())
    db.commit(); db.refresh(item); return item


def get_invitation(db: Session, organization_id: UUID, invitation_id: UUID) -> ExternalPortalInvitation:
    item = db.scalar(select(ExternalPortalInvitation).where(
        ExternalPortalInvitation.id == invitation_id,
        ExternalPortalInvitation.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Portal invitation not found")
    return item


def revoke_invitation(db: Session, item: ExternalPortalInvitation, user: User, note: str) -> ExternalPortalInvitation:
    if item.status == "revoked":
        return item
    item.status = "revoked"; item.revoked_at = datetime.now(UTC)
    sessions = list(db.scalars(select(ExternalPortalSession).where(ExternalPortalSession.invitation_id == item.id)))
    for session in sessions:
        session.revoked_at = item.revoked_at
    _audit(db, org=item.organization_id, user=user.id, action="REVOKE_EXTERNAL_PORTAL_INVITATION",
           kind="external_portal_invitation", entity=item.id, values={"status": item.status}, details=note.strip())
    db.commit(); db.refresh(item)
    return item


def accept_invitation(db: Session, token: str) -> tuple[str, datetime]:
    token_hash = sha256(token.encode()).hexdigest()
    item = db.scalar(select(ExternalPortalInvitation).where(ExternalPortalInvitation.token_hash == token_hash))
    now = datetime.now(UTC)
    if item is None or not compare_digest(item.token_hash, token_hash):
        raise HTTPException(401, "Invalid portal invitation")
    invitation_expires = _utc(item.expires_at)
    if item.status != "pending" or invitation_expires <= now:
        if invitation_expires <= now and item.status == "pending":
            item.status = "expired"; db.commit()
        raise HTTPException(410, "Portal invitation is unavailable")
    session_token = secrets.token_urlsafe(32); session_expires = min(invitation_expires, now + timedelta(hours=12))
    session = ExternalPortalSession(
        organization_id=item.organization_id, invitation_id=item.id,
        session_hash=sha256(session_token.encode()).hexdigest(), expires_at=session_expires,
        last_seen_at=now,
    )
    item.status = "accepted"; item.accepted_at = now
    db.add(session); db.flush()
    _audit(db, org=item.organization_id, user=None, action="ACCEPT_EXTERNAL_PORTAL_INVITATION",
           kind="external_portal_invitation", entity=item.id,
           values={"status": item.status, "session_expires_at": session_expires.isoformat()},
           details="One-time invitation exchanged for a separately hashed expiring session.")
    db.commit()
    return session_token, session_expires


def authenticate_session(db: Session, token: str | None) -> tuple[ExternalPortalSession, ExternalPortalInvitation]:
    value = sha256((token or "").encode()).hexdigest()
    session = db.scalar(select(ExternalPortalSession).where(ExternalPortalSession.session_hash == value))
    now = datetime.now(UTC)
    if session is None or not token or not compare_digest(session.session_hash, value):
        raise HTTPException(401, "Invalid portal session")
    invitation = db.get(ExternalPortalInvitation, session.invitation_id)
    if (session.revoked_at is not None or _utc(session.expires_at) <= now or invitation is None
            or invitation.status != "accepted" or _utc(invitation.expires_at) <= now):
        raise HTTPException(410, "Portal session has expired or been revoked")
    session.last_seen_at = now; db.commit()
    return session, invitation


def portal_view(db: Session, invitation: ExternalPortalInvitation) -> dict:
    claim = db.get(Claim, invitation.claim_id); vessel = db.get(Vessel, claim.vessel_id)
    submissions = list(db.scalars(select(ExternalPortalSubmission).where(
        ExternalPortalSubmission.invitation_id == invitation.id,
    ).order_by(ExternalPortalSubmission.submitted_at.desc())))
    return {"claim_reference": claim.claim_reference, "vessel_name": vessel.name,
            "incident_date": claim.incident_date, "incident_description": claim.incident_description,
            "participant_name": invitation.participant_name, "purpose": invitation.purpose,
            "permission_manifest": invitation.permission_manifest,
            "published_items": _published(db, invitation.id), "submissions": submissions}


def create_submission(db: Session, invitation: ExternalPortalInvitation,
                      payload: PortalSubmissionCreate) -> ExternalPortalSubmission:
    if "submission.create" not in invitation.permission_manifest:
        raise HTTPException(403, "This invitation does not permit submissions")
    manifests = [{**item.model_dump(), "sha256": item.sha256.lower() if item.sha256 else None,
                  "admission_status": "blocked_pending_quarantine"}
                 for item in payload.attachment_manifests]
    item = ExternalPortalSubmission(
        organization_id=invitation.organization_id, claim_id=invitation.claim_id,
        invitation_id=invitation.id, subject=payload.subject.strip(), body=payload.body,
        attachment_manifests=manifests, status="pending_review", submitted_at=datetime.now(UTC),
    )
    db.add(item); db.flush()
    _audit(db, org=item.organization_id, user=None, action="SUBMIT_EXTERNAL_PORTAL_MESSAGE",
           kind="external_portal_submission", entity=item.id,
           values={"claim_id": str(item.claim_id), "attachment_count": len(manifests), "status": item.status},
           details="External content staged for human review; attachment bytes were not accepted.")
    db.commit(); db.refresh(item)
    return item


def get_submission(db: Session, organization_id: UUID, submission_id: UUID) -> ExternalPortalSubmission:
    item = db.scalar(select(ExternalPortalSubmission).where(
        ExternalPortalSubmission.id == submission_id,
        ExternalPortalSubmission.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Portal submission not found")
    return item


def review_submission(db: Session, item: ExternalPortalSubmission, user: User,
                      payload: PortalReview) -> ExternalPortalSubmission:
    if item.status != "pending_review":
        raise HTTPException(409, "Only pending portal submissions can be reviewed")
    item.review_note = payload.note.strip(); item.reviewed_at = datetime.now(UTC); item.reviewed_by_id = user.id
    if payload.action == "reject":
        item.status = "rejected"
    else:
        invitation = db.get(ExternalPortalInvitation, item.invitation_id)
        correspondence = ClaimCorrespondence(
            organization_id=item.organization_id, claim_id=item.claim_id, created_by_id=user.id,
            direction=CorrespondenceDirection.INBOUND, kind=CorrespondenceKind.GENERAL,
            status=CorrespondenceStatus.RECEIVED_EXTERNAL, sensitivity=CorrespondenceSensitivity.STANDARD,
            channel=CorrespondenceChannel.PORTAL, sender_label=invitation.participant_name[:180],
            recipient_label="Claims team", subject=item.subject, body=item.body,
            requirement_ids=[], external_reference=f"portal-submission:{item.id}", occurred_at=item.submitted_at,
        )
        db.add(correspondence); db.flush()
        item.status = "promoted"; item.correspondence_id = correspondence.id
    _audit(db, org=item.organization_id, user=user.id,
           action="PROMOTE_EXTERNAL_PORTAL_SUBMISSION" if item.status == "promoted" else "REJECT_EXTERNAL_PORTAL_SUBMISSION",
           kind="external_portal_submission", entity=item.id,
           values={"status": item.status, "correspondence_id": str(item.correspondence_id) if item.correspondence_id else None},
           details=payload.note.strip() + " Attachment manifests remain blocked pending quarantine admission.")
    db.commit(); db.refresh(item)
    return item

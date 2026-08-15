from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ExternalPortalInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_portal_invitations"
    __table_args__ = (Index("ix_external_portal_invite_org_claim_status", "organization_id", "claim_id", "status"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    participant_name: Mapped[str] = mapped_column(String(180))
    participant_email: Mapped[str] = mapped_column(String(320))
    purpose: Mapped[str] = mapped_column(Text)
    permission_manifest: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalPortalSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_portal_sessions"

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    invitation_id: Mapped[UUID] = mapped_column(ForeignKey("external_portal_invitations.id", ondelete="CASCADE"), index=True)
    session_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalPortalPublishedItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_portal_published_items"
    __table_args__ = (
        UniqueConstraint("invitation_id", "item_type", "source_id", name="uq_external_portal_published_source"),
        Index("ix_external_portal_published_invite", "invitation_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    invitation_id: Mapped[UUID] = mapped_column(ForeignKey("external_portal_invitations.id", ondelete="CASCADE"), index=True)
    published_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    item_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[UUID] = mapped_column()
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExternalPortalSubmission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_portal_submissions"
    __table_args__ = (Index("ix_external_portal_submission_org_claim_status", "organization_id", "claim_id", "status"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    invitation_id: Mapped[UUID] = mapped_column(ForeignKey("external_portal_invitations.id", ondelete="RESTRICT"), index=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    correspondence_id: Mapped[UUID | None] = mapped_column(ForeignKey("claim_correspondence.id", ondelete="SET NULL"), nullable=True)
    subject: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text)
    attachment_manifests: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="pending_review", server_default="pending_review")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

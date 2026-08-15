import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class EmailConnectionStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class EmailMessageStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    LINKED = "linked"
    REJECTED = "rejected"
    EXPIRED = "expired"


class EmailIngestionConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_ingestion_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", "mailbox_address", name="uq_email_connection_org_mailbox"),
        Index("ix_email_connection_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    provider_label: Mapped[str] = mapped_column(String(80))
    mailbox_address: Mapped[str] = mapped_column(String(320))
    status: Mapped[EmailConnectionStatus] = mapped_column(Enum(EmailConnectionStatus, name="email_connection_status", native_enum=True, values_callable=enum_values), default=EmailConnectionStatus.ACTIVE, server_default=EmailConnectionStatus.ACTIVE.value)
    consent_basis: Mapped[str] = mapped_column(Text)
    consent_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retention_days: Mapped[int] = mapped_column(Integer)
    token_hash: Mapped[str] = mapped_column(String(64))
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestedEmailMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ingested_email_messages"
    __table_args__ = (
        UniqueConstraint("connection_id", "provider_message_id", name="uq_ingested_email_provider_message"),
        Index("ix_ingested_email_org_status_received", "organization_id", "status", "received_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("email_ingestion_connections.id", ondelete="RESTRICT"), index=True)
    suggested_claim_id: Mapped[UUID | None] = mapped_column(ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True)
    linked_claim_id: Mapped[UUID | None] = mapped_column(ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True)
    linked_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    correspondence_id: Mapped[UUID | None] = mapped_column(ForeignKey("claim_correspondence.id", ondelete="SET NULL"), nullable=True)
    provider_message_id: Mapped[str] = mapped_column(String(240))
    internet_message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sender: Mapped[str] = mapped_column(String(500))
    recipients: Mapped[list] = mapped_column(JSON)
    cc: Mapped[list] = mapped_column(JSON)
    subject: Mapped[str] = mapped_column(String(500))
    body_text: Mapped[str] = mapped_column(Text)
    status: Mapped[EmailMessageStatus] = mapped_column(Enum(EmailMessageStatus, name="email_message_status", native_enum=True, values_callable=enum_values), default=EmailMessageStatus.PENDING_REVIEW, server_default=EmailMessageStatus.PENDING_REVIEW.value)
    content_hash: Mapped[str] = mapped_column(String(64))
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailAttachmentManifest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_attachment_manifests"
    __table_args__ = (Index("ix_email_attachment_message", "message_id", "created_at"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("ingested_email_messages.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(150))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    provider_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    admission_status: Mapped[str] = mapped_column(String(60), default="blocked_pending_quarantine", server_default="blocked_pending_quarantine")


class EmailProviderAdapter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_provider_adapters"
    __table_args__ = (
        UniqueConstraint("connection_id", name="uq_email_provider_adapter_connection"),
        Index("ix_email_provider_adapter_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("email_ingestion_connections.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    provider_kind: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(100))
    credential_reference: Mapped[str] = mapped_column(String(240))
    allowed_folder: Mapped[str] = mapped_column(String(240))
    permission_manifest: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")
    batch_limit: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    retention_schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoint_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailAdapterRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_adapter_runs"
    __table_args__ = (
        UniqueConstraint("adapter_id", "idempotency_key", name="uq_email_adapter_run_idempotency"),
        Index("ix_email_adapter_run_org_started", "organization_id", "started_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    adapter_id: Mapped[UUID] = mapped_column(ForeignKey("email_provider_adapters.id", ondelete="RESTRICT"), index=True)
    initiated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    trigger: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    messages_seen: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    messages_ingested: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    checkpoint_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailRetentionRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_retention_runs"
    __table_args__ = (UniqueConstraint("organization_id", "idempotency_key", name="uq_email_retention_run_idempotency"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    initiated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    expired_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

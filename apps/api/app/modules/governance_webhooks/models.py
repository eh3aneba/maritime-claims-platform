from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class GovernanceWebhookDestination(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "governance_webhook_destinations"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_gwd_org_name"),
        Index("ix_gwd_org_enabled", "organization_id", "enabled", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    event_types: Mapped[list] = mapped_column(JSON, nullable=False)

    # Secret material is never persisted. The server derives the active HMAC key
    # from the application master secret plus this non-secret salt/version tuple.
    secret_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    secret_reference: Mapped[str] = mapped_column(String(180), nullable=False)
    previous_secret_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_secret_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_secret_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(40), nullable=True)


class GovernanceWebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "governance_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "destination_id",
            "source_workflow_type",
            "source_event_id",
            "source_revision_hash",
            "envelope_version",
            name="uq_gwdel_source_revision",
        ),
        Index("ix_gwdel_org_status", "organization_id", "status", "next_attempt_at"),
        Index("ix_gwdel_destination", "destination_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    destination_id: Mapped[UUID] = mapped_column(
        ForeignKey("governance_webhook_destinations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_workflow_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(nullable=False)
    source_revision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    envelope_version: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # This is an explicit content-free allowlisted snapshot used for reliable retries.
    envelope: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_version: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", server_default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=6, server_default="6")
    manual_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

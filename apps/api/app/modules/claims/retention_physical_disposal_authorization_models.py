from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PhysicalDisposalAdmissionAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bounded, four-eyes admission credential for a future physical-disposal executor.

    Phase 17.4-A never mutates or deletes evidence. The credential is claim-scoped
    and carries an immutable binding set for every document in the approved
    disposal manifest.
    """

    __tablename__ = "physical_disposal_admission_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "disposal_release_review_id",
            name="uq_physical_disposal_admission_release_review",
        ),
        UniqueConstraint(
            "organization_id",
            "authorization_hash",
            name="uq_physical_disposal_admission_org_hash",
        ),
        CheckConstraint(
            "status IN ('pending_second_approval','authorized','rejected','expired','invalidated','consumed')",
            name="ck_physical_disposal_admission_status",
        ),
        CheckConstraint(
            "max_execution_count = 1",
            name="ck_physical_disposal_admission_single_use",
        ),
        CheckConstraint(
            "execution_count IN (0, 1)",
            name="ck_physical_disposal_admission_execution_count",
        ),
        CheckConstraint(
            "(status = 'pending_second_approval' AND physical_disposal_authorized = false "
            "AND execution_count = 0 AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'authorized' AND physical_disposal_authorized = true "
            "AND execution_count = 0 AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL "
            "AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL AND terminal_by_id IS NULL "
            "AND terminal_at IS NULL AND terminal_reason IS NULL) OR "
            "(status = 'consumed' AND physical_disposal_authorized = true "
            "AND execution_count = 1 AND approved_by_id IS NOT NULL AND approved_at IS NOT NULL "
            "AND approval_reason IS NOT NULL AND approval_hash IS NOT NULL) OR "
            "(status IN ('rejected','expired','invalidated') AND physical_disposal_authorized = false "
            "AND execution_count = 0 AND approved_by_id IS NULL AND approved_at IS NULL "
            "AND approval_reason IS NULL AND approval_hash IS NULL AND terminal_by_id IS NOT NULL "
            "AND terminal_at IS NOT NULL AND terminal_reason IS NOT NULL)",
            name="ck_physical_disposal_admission_lifecycle",
        ),
        CheckConstraint(
            "approved_by_id IS NULL OR approved_by_id <> requested_by_id",
            name="ck_physical_disposal_admission_four_eyes",
        ),
        CheckConstraint(
            "document_count > 0",
            name="ck_physical_disposal_admission_document_count",
        ),
        CheckConstraint(
            "total_file_size_bytes >= 0",
            name="ck_physical_disposal_admission_total_bytes",
        ),
        CheckConstraint(
            "authorization_expires_at > requested_at",
            name="ck_physical_disposal_admission_expiry",
        ),
        CheckConstraint(
            "destructive_action_performed = false",
            name="ck_physical_disposal_admission_no_destructive_action",
        ),
        CheckConstraint(
            "storage_write_performed = false",
            name="ck_physical_disposal_admission_no_storage_write",
        ),
        CheckConstraint(
            "s3_delete_performed = false",
            name="ck_physical_disposal_admission_no_s3_delete",
        ),
        CheckConstraint(
            "local_delete_performed = false",
            name="ck_physical_disposal_admission_no_local_delete",
        ),
        Index(
            "ix_physical_disposal_admission_org_claim_status",
            "organization_id",
            "claim_id",
            "status",
        ),
        Index(
            "ix_physical_disposal_admission_org_expiry",
            "organization_id",
            "authorization_expires_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    disposal_release_review_id: Mapped[UUID] = mapped_column(
        ForeignKey("disposal_release_reviews.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    disposal_quarantine_stage_id: Mapped[UUID] = mapped_column(
        ForeignKey("disposal_quarantine_stages.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    disposal_execution_manifest_id: Mapped[UUID] = mapped_column(
        ForeignKey("disposal_execution_manifests.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    release_review_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release_approval_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    inventory_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_bindings: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    document_bindings_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    requested_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_second_approval",
        server_default="pending_second_approval",
    )
    physical_disposal_authorized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    max_execution_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    execution_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    approved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    terminal_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    destructive_action_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    storage_write_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    s3_delete_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    local_delete_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

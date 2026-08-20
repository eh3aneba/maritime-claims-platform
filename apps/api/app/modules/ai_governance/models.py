from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AIProviderActivationRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_provider_activation_requests"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_ai_provider_activation_key"),
        UniqueConstraint("organization_id", "environment", "provider", "attempt_number",
                         name="uq_ai_provider_activation_attempt"),
        Index("ix_ai_provider_activation_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(120))
    environment: Mapped[str] = mapped_column(String(30), default="staging", server_default="staging")
    provider: Mapped[str] = mapped_column(String(40), default="openai", server_default="openai")
    provider_project_label: Mapped[str] = mapped_column(String(180))
    model: Mapped[str] = mapped_column(String(120))
    prompt_bundle_version: Mapped[str] = mapped_column(String(80))
    schema_bundle_version: Mapped[str] = mapped_column(String(80))
    data_mode: Mapped[str] = mapped_column(String(40), default="synthetic_deidentified",
                                           server_default="synthetic_deidentified")
    allowed_document_types: Mapped[list] = mapped_column(JSON)
    restricted_documents_allowed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    credential_storage_mode: Mapped[str] = mapped_column(String(40))
    max_input_chars: Mapped[int] = mapped_column(Integer)
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    requests_per_minute: Mapped[int] = mapped_column(Integer)
    tokens_per_minute: Mapped[int] = mapped_column(Integer)
    monthly_spend_limit_cents: Mapped[int] = mapped_column(Integer)
    spend_alert_thresholds: Mapped[list] = mapped_column(JSON)
    retention_mode: Mapped[str] = mapped_column(String(50))
    data_residency_region: Mapped[str] = mapped_column(String(160))
    security_owner_label: Mapped[str] = mapped_column(String(180))
    privacy_owner_label: Mapped[str] = mapped_column(String(180))
    product_owner_label: Mapped[str] = mapped_column(String(180))
    incident_owner_label: Mapped[str] = mapped_column(String(180))
    kill_switch_owner_label: Mapped[str] = mapped_column(String(180))
    credential_control_reference: Mapped[str] = mapped_column(String(500))
    spend_limit_reference: Mapped[str] = mapped_column(String(500))
    data_processing_reference: Mapped[str] = mapped_column(String(500))
    kill_switch_reference: Mapped[str] = mapped_column(String(500))
    evaluation_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="pending_approvals",
                                        server_default="pending_approvals")
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AIProviderActivationApproval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_provider_activation_approvals"
    __table_args__ = (
        UniqueConstraint("activation_request_id", "approval_role",
                         name="uq_ai_provider_activation_approval_role"),
        Index("ix_ai_provider_approval_org_request", "organization_id", "activation_request_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    activation_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_provider_activation_requests.id", ondelete="CASCADE"), index=True)
    approver_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approval_role: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIDocumentEligibilityAttestation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_document_eligibility_attestations"
    __table_args__ = (
        UniqueConstraint("document_id", "attestation_number", name="uq_ai_document_eligibility_attempt"),
        Index("ix_ai_document_eligibility_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    activation_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_provider_activation_requests.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), index=True)
    attested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attestation_number: Mapped[int] = mapped_column(Integer)
    data_mode: Mapped[str] = mapped_column(String(30))
    document_type: Mapped[str] = mapped_column(String(100))
    confidentiality_level: Mapped[str] = mapped_column(String(30))
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="eligible", server_default="eligible")
    attested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_note: Mapped[str | None] = mapped_column(Text, nullable=True)

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AIBroaderProductionAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_broader_production_authorizations"
    __table_args__ = (
        UniqueConstraint("organization_id", "authorization_key", name="uq_ai_bp_org_key"),
        UniqueConstraint("readiness_assessment_id", "attempt_number", name="uq_ai_bp_attempt"),
        Index("ix_ai_bp_org_status", "organization_id", "status", "created_at"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    readiness_assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_scale_up_outcome_assessments.id", ondelete="RESTRICT"), index=True)
    scale_up_authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_scale_up_authorizations.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    authorization_key: Mapped[str] = mapped_column(String(120))
    environment: Mapped[str] = mapped_column(String(30), default="production", server_default="production")
    authorization_mode: Mapped[str] = mapped_column(String(60), default="broader_production_bounded", server_default="broader_production_bounded")
    readiness_assessment_hash: Mapped[str] = mapped_column(String(64))
    readiness_decision_hash: Mapped[str] = mapped_column(String(64))
    scale_up_decision_hash: Mapped[str] = mapped_column(String(64))
    inherited_outcome_assessment_hash: Mapped[str] = mapped_column(String(64))
    inherited_outcome_decision_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(120))
    prompt_bundle_version: Mapped[str] = mapped_column(String(80))
    schema_bundle_version: Mapped[str] = mapped_column(String(80))
    max_input_chars: Mapped[int] = mapped_column(Integer)
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    allowed_document_types: Mapped[list] = mapped_column(JSON)
    previous_rollout_percentage: Mapped[int] = mapped_column(Integer)
    rollout_percentage: Mapped[int] = mapped_column(Integer)
    max_claims: Mapped[int] = mapped_column(Integer)
    max_documents: Mapped[int] = mapped_column(Integer)
    max_users: Mapped[int] = mapped_column(Integer)
    max_provider_runs: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rollback_slo_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    monitor_interval_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    max_reject_rate_bps: Mapped[int] = mapped_column(Integer, default=800, server_default="800")
    max_edit_rate_bps: Mapped[int] = mapped_column(Integer, default=3000, server_default="3000")
    max_unsupported_output_rate_bps: Mapped[int] = mapped_column(Integer, default=75, server_default="75")
    min_source_grounding_validity_bps: Mapped[int] = mapped_column(Integer, default=9925, server_default="9925")
    max_p95_latency_ms: Mapped[int] = mapped_column(Integer, default=20000, server_default="20000")
    max_mean_cost_microusd: Mapped[int] = mapped_column(Integer, default=500000, server_default="500000")
    max_quality_regression_bps: Mapped[int] = mapped_column(Integer, default=300, server_default="300")
    max_latency_regression_bps: Mapped[int] = mapped_column(Integer, default=1500, server_default="1500")
    max_cost_regression_bps: Mapped[int] = mapped_column(Integer, default=1500, server_default="1500")
    deployment_isolation_reference: Mapped[str] = mapped_column(String(500))
    provider_project_reference: Mapped[str] = mapped_column(String(500))
    credential_control_reference: Mapped[str] = mapped_column(String(500))
    privacy_legal_reference: Mapped[str] = mapped_column(String(500))
    monitoring_reference: Mapped[str] = mapped_column(String(500))
    incident_response_reference: Mapped[str] = mapped_column(String(500))
    rollback_reference: Mapped[str] = mapped_column(String(500))
    change_ticket_reference: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="pending_approvals", server_default="pending_approvals")
    outcome: Mapped[str | None] = mapped_column(String(60), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AIBroaderProductionApproval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_broader_production_approvals"
    __table_args__ = (
        UniqueConstraint("authorization_id", "approval_role", name="uq_ai_bp_approval_role"),
        Index("ix_ai_bp_approval_org", "organization_id", "authorization_id"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_broader_production_authorizations.id", ondelete="CASCADE"), index=True)
    approver_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approval_role: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIBroaderProductionDocumentEligibility(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_broader_production_document_eligibility"
    __table_args__ = (
        UniqueConstraint("authorization_id", "document_id", "attestation_number", name="uq_ai_bp_doc_attempt"),
        Index("ix_ai_bp_doc_org", "organization_id", "authorization_id", "status"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_broader_production_authorizations.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), index=True)
    attested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attestation_number: Mapped[int] = mapped_column(Integer)
    rollout_bucket: Mapped[int] = mapped_column(Integer)
    document_type: Mapped[str] = mapped_column(String(100))
    confidentiality_level: Mapped[str] = mapped_column(String(30))
    legal_basis_reference: Mapped[str] = mapped_column(String(500))
    data_minimization_reference: Mapped[str] = mapped_column(String(500))
    change_ticket_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="eligible", server_default="eligible")
    attested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AIBroaderProductionRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_broader_production_runs"
    __table_args__ = (
        UniqueConstraint("authorization_id", "run_key", name="uq_ai_bp_run_key"),
        UniqueConstraint("processing_job_id", name="uq_ai_bp_processing_job"),
        Index("ix_ai_bp_run_org", "organization_id", "authorization_id", "status"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_broader_production_authorizations.id", ondelete="CASCADE"), index=True)
    eligibility_id: Mapped[UUID] = mapped_column(ForeignKey("ai_broader_production_document_eligibility.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    run_key: Mapped[str] = mapped_column(String(120))
    processing_job_id: Mapped[UUID] = mapped_column(ForeignKey("document_processing_jobs.id", ondelete="RESTRICT"), index=True)
    task_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="queued", server_default="queued")
    human_review_action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    output_candidate_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    human_edit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unsupported_output_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_grounded_output_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_grounding_total_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_provider_cost_microusd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIBroaderProductionMonitor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_broader_production_monitors"
    __table_args__ = (
        UniqueConstraint("authorization_id", "monitor_key", name="uq_ai_bp_monitor_key"),
        Index("ix_ai_bp_monitor_org", "organization_id", "authorization_id", "monitored_at"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_broader_production_authorizations.id", ondelete="CASCADE"), index=True)
    initiated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    monitor_key: Mapped[str] = mapped_column(String(120))
    metrics: Mapped[dict] = mapped_column(JSON)
    failure_reasons: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30))
    monitor_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text)
    monitored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIBroaderProductionIncident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_broader_production_incidents"
    __table_args__ = (Index("ix_ai_bp_incident_org", "organization_id", "authorization_id", "status"),)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_broader_production_authorizations.id", ondelete="CASCADE"), index=True)
    reported_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    severity: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(40))
    evidence_reference: Mapped[str] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

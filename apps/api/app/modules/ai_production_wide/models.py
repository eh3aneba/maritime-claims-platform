from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AIProductionWideAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_production_wide_authorizations"
    __table_args__ = (
        UniqueConstraint("organization_id", "authorization_key", name="uq_ai_pwa_org_key"),
        UniqueConstraint("bounded_full_outcome_assessment_id", "attempt_number", name="uq_ai_pwa_attempt"),
        Index("ix_ai_pwa_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    bounded_full_outcome_assessment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_bounded_full_production_outcome_assessments.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    attempt_number: Mapped[int] = mapped_column(Integer)
    authorization_key: Mapped[str] = mapped_column(String(120))
    environment: Mapped[str] = mapped_column(String(30), default="production", server_default="production")
    authorization_mode: Mapped[str] = mapped_column(String(80), default="production_wide_human_reviewed", server_default="production_wide_human_reviewed")

    bounded_full_outcome_assessment_hash: Mapped[str] = mapped_column(String(64))
    bounded_full_outcome_decision_hash: Mapped[str] = mapped_column(String(64))
    bounded_full_decision_hash: Mapped[str] = mapped_column(String(64))
    bounded_full_completion_hash: Mapped[str] = mapped_column(String(64))

    model: Mapped[str] = mapped_column(String(120))
    prompt_bundle_version: Mapped[str] = mapped_column(String(80))
    schema_bundle_version: Mapped[str] = mapped_column(String(80))
    max_input_chars: Mapped[int] = mapped_column(Integer)
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    allowed_document_types: Mapped[list] = mapped_column(JSON)

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    monitor_interval_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    rollback_slo_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")

    eligibility_policy_version: Mapped[str] = mapped_column(String(80))
    eligibility_policy_reference: Mapped[str] = mapped_column(String(500))
    legal_basis_policy_reference: Mapped[str] = mapped_column(String(500))
    data_minimization_policy_reference: Mapped[str] = mapped_column(String(500))
    deployment_isolation_reference: Mapped[str] = mapped_column(String(500))
    provider_project_reference: Mapped[str] = mapped_column(String(500))
    credential_control_reference: Mapped[str] = mapped_column(String(500))
    monitoring_reference: Mapped[str] = mapped_column(String(500))
    incident_response_reference: Mapped[str] = mapped_column(String(500))
    rollback_reference: Mapped[str] = mapped_column(String(500))
    model_change_control_reference: Mapped[str] = mapped_column(String(500))
    internal_audit_reference: Mapped[str] = mapped_column(String(500))
    change_ticket_reference: Mapped[str] = mapped_column(String(500))
    policy_hash: Mapped[str] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(30), default="pending_approvals", server_default="pending_approvals")
    outcome: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AIProductionWideApproval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_production_wide_approvals"
    __table_args__ = (
        UniqueConstraint("authorization_id", "approval_role", name="uq_ai_pwa_approval_role"),
        Index("ix_ai_pwa_approval_org", "organization_id", "authorization_id"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_production_wide_authorizations.id", ondelete="CASCADE"), index=True)
    approver_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approval_role: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIProductionEligibilityDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_production_eligibility_decisions"
    __table_args__ = (
        UniqueConstraint("authorization_id", "document_id", "policy_hash", name="uq_ai_pwe_doc_policy"),
        Index("ix_ai_pwe_org", "organization_id", "authorization_id", "eligible"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_production_wide_authorizations.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), index=True)
    document_type: Mapped[str] = mapped_column(String(100))
    confidentiality_level: Mapped[str] = mapped_column(String(30))
    eligible: Mapped[bool] = mapped_column(Boolean)
    reason_codes: Mapped[list] = mapped_column(JSON)
    policy_hash: Mapped[str] = mapped_column(String(64))
    decision_hash: Mapped[str] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIProductionDecisionLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_production_decision_logs"
    __table_args__ = (
        UniqueConstraint("processing_job_id", name="uq_ai_pwdl_processing_job"),
        UniqueConstraint("authorization_id", "run_key", name="uq_ai_pwdl_run_key"),
        Index("ix_ai_pwdl_org", "organization_id", "authorization_id", "status"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_production_wide_authorizations.id", ondelete="CASCADE"), index=True)
    eligibility_decision_id: Mapped[UUID] = mapped_column(ForeignKey("ai_production_eligibility_decisions.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), index=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    run_key: Mapped[str] = mapped_column(String(120))
    processing_job_id: Mapped[UUID] = mapped_column(ForeignKey("document_processing_jobs.id", ondelete="RESTRICT"), index=True)
    task_type: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(120))
    prompt_bundle_version: Mapped[str] = mapped_column(String(80))
    schema_bundle_version: Mapped[str] = mapped_column(String(80))
    authorization_hash: Mapped[str] = mapped_column(String(64))
    eligibility_policy_hash: Mapped[str] = mapped_column(String(64))
    eligibility_decision_hash: Mapped[str] = mapped_column(String(64))
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
    run_hash: Mapped[str] = mapped_column(String(64))
    review_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIProductionWideMonitor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_production_wide_monitors"
    __table_args__ = (
        UniqueConstraint("authorization_id", "monitor_key", name="uq_ai_pwm_monitor_key"),
        Index("ix_ai_pwm_org", "organization_id", "authorization_id", "monitored_at"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_production_wide_authorizations.id", ondelete="CASCADE"), index=True)
    initiated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    monitor_key: Mapped[str] = mapped_column(String(120))
    metrics: Mapped[dict] = mapped_column(JSON)
    failure_reasons: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))
    monitor_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text)
    monitored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIProductionWideIncident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_production_wide_incidents"
    __table_args__ = (Index("ix_ai_pwi_org", "organization_id", "authorization_id", "status"),)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("ai_production_wide_authorizations.id", ondelete="CASCADE"), index=True)
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

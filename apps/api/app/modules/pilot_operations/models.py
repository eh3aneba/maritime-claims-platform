from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DeploymentReadinessReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deployment_readiness_reviews"
    __table_args__ = (
        UniqueConstraint("organization_id", "environment", "review_key", name="uq_deployment_readiness_review_key"),
        Index("ix_deployment_readiness_org_environment", "organization_id", "environment", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    environment: Mapped[str] = mapped_column(String(30))
    review_key: Mapped[str] = mapped_column(String(120))
    controls: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="draft", server_default="draft")
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    attestation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    attested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OperationalMonitorRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operational_monitor_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_operational_monitor_run_key"),
        Index("ix_operational_monitor_org_run", "organization_id", "run_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    initiated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    metrics: Mapped[dict] = mapped_column(JSON)
    alerts: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OperationalIncident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operational_incidents"
    __table_args__ = (Index("ix_operational_incident_org_status_severity", "organization_id", "status", "severity"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    monitor_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("operational_monitor_runs.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    severity: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    owner_label: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(30), default="open", server_default="open")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PilotGovernanceProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pilot_governance_profiles"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_pilot_governance_profile_org"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    pilot_purpose: Mapped[str] = mapped_column(Text)
    legal_basis: Mapped[str] = mapped_column(Text)
    data_owner: Mapped[str] = mapped_column(String(180))
    retention_statement: Mapped[str] = mapped_column(Text)
    residency_statement: Mapped[str] = mapped_column(Text)
    exit_contact: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(30), default="draft", server_default="draft")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PilotExitManifest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pilot_exit_manifests"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "idempotency_key", name="uq_pilot_exit_manifest_key"),
        Index("ix_pilot_exit_manifest_org_claim", "organization_id", "claim_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    governance_profile_id: Mapped[UUID] = mapped_column(ForeignKey("pilot_governance_profiles.id", ondelete="RESTRICT"))
    authorized_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    confirm_manifest_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    manifest: Mapped[dict] = mapped_column(JSON)
    manifest_checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="authorized", server_default="authorized")
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DesignPartnerRehearsal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "design_partner_rehearsals"
    __table_args__ = (
        UniqueConstraint("organization_id", "rehearsal_key", name="uq_design_partner_rehearsal_key"),
        Index("ix_design_partner_rehearsal_org_status", "organization_id", "status", "scheduled_for"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    readiness_review_id: Mapped[UUID] = mapped_column(ForeignKey("deployment_readiness_reviews.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rehearsal_key: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    objectives: Mapped[list] = mapped_column(JSON)
    participant_roles: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="draft", server_default="draft")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RehearsalControlEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rehearsal_control_evidence"
    __table_args__ = (
        UniqueConstraint("rehearsal_id", "control_key", name="uq_rehearsal_control_evidence"),
        Index("ix_rehearsal_evidence_org_rehearsal", "organization_id", "rehearsal_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    rehearsal_id: Mapped[UUID] = mapped_column(ForeignKey("design_partner_rehearsals.id", ondelete="CASCADE"), index=True)
    recorded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    control_key: Mapped[str] = mapped_column(String(50))
    evidence_reference: Mapped[str] = mapped_column(String(500))
    evidence_summary: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(30))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RehearsalRemediationFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rehearsal_remediation_findings"
    __table_args__ = (Index("ix_rehearsal_finding_org_status", "organization_id", "rehearsal_id", "status"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    rehearsal_id: Mapped[UUID] = mapped_column(ForeignKey("design_partner_rehearsals.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[UUID | None] = mapped_column(ForeignKey("rehearsal_control_evidence.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    severity: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    owner_label: Mapped[str] = mapped_column(String(180))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="open", server_default="open")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PrivatePilotExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "private_pilot_executions"
    __table_args__ = (
        UniqueConstraint("organization_id", "execution_key", name="uq_private_pilot_execution_key"),
        UniqueConstraint("rehearsal_id", name="uq_private_pilot_execution_rehearsal"),
        Index("ix_private_pilot_execution_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    rehearsal_id: Mapped[UUID] = mapped_column(ForeignKey("design_partner_rehearsals.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    execution_key: Mapped[str] = mapped_column(String(120))
    design_partner_label: Mapped[str] = mapped_column(String(200))
    data_mode: Mapped[str] = mapped_column(String(30))
    data_authorization_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    objectives: Mapped[list] = mapped_column(JSON)
    target_case_runs: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft", server_default="draft")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PrivatePilotCaseRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "private_pilot_case_runs"
    __table_args__ = (
        UniqueConstraint("execution_id", "claim_id", name="uq_private_pilot_case_claim"),
        Index("ix_private_pilot_case_org_execution", "organization_id", "execution_id", "recorded_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("private_pilot_executions.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), index=True)
    recorded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    case_outcome: Mapped[str] = mapped_column(String(30))
    evidence_reference: Mapped[str] = mapped_column(String(500))
    triage_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_review_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assessment_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adjustment_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_candidates_reviewed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ai_accepted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ai_edited: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ai_rejected: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rule_findings_reviewed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rule_findings_helpful: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    open_conflicts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    open_requirements: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProductGapFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_gap_findings"
    __table_args__ = (Index("ix_product_gap_org_execution_status", "organization_id", "execution_id", "status"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("private_pilot_executions.id", ondelete="CASCADE"), index=True)
    case_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("private_pilot_case_runs.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    priority: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    owner_label: Mapped[str] = mapped_column(String(180))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open", server_default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductionArchitectureBaseline(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "production_architecture_baselines"
    __table_args__ = (
        UniqueConstraint("organization_id", "baseline_key", name="uq_production_architecture_baseline_key"),
        Index("ix_production_architecture_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    pilot_execution_id: Mapped[UUID] = mapped_column(ForeignKey("private_pilot_executions.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attested_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    baseline_key: Mapped[str] = mapped_column(String(120))
    deployment_model: Mapped[str] = mapped_column(String(40))
    data_residency_region: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="draft", server_default="draft")
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attestation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    attested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductionArchitectureControl(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "production_architecture_controls"
    __table_args__ = (
        UniqueConstraint("baseline_id", "control_key", name="uq_production_architecture_control"),
        Index("ix_production_architecture_control_org", "organization_id", "baseline_id", "current_state"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    baseline_id: Mapped[UUID] = mapped_column(ForeignKey("production_architecture_baselines.id", ondelete="CASCADE"), index=True)
    recorded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    control_key: Mapped[str] = mapped_column(String(50))
    current_state: Mapped[str] = mapped_column(String(30))
    target_architecture: Mapped[str] = mapped_column(Text)
    risk_note: Mapped[str] = mapped_column(Text)
    owner_label: Mapped[str] = mapped_column(String(180))
    target_date: Mapped[date] = mapped_column(Date)
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ProductionControlVerificationGate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "production_control_verification_gates"
    __table_args__ = (
        UniqueConstraint("organization_id", "gate_key", name="uq_production_control_gate_key"),
        UniqueConstraint("architecture_baseline_id", name="uq_production_control_gate_baseline"),
        Index("ix_production_control_gate_org_status", "organization_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    architecture_baseline_id: Mapped[UUID] = mapped_column(ForeignKey("production_architecture_baselines.id", ondelete="RESTRICT"))
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    gate_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="collecting", server_default="collecting")
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductionControlEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "production_control_evidence"
    __table_args__ = (
        UniqueConstraint("gate_id", "control_key", "submission_version", name="uq_production_control_evidence_version"),
        Index("ix_production_control_evidence_org_gate", "organization_id", "gate_id", "control_key"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    gate_id: Mapped[UUID] = mapped_column(ForeignKey("production_control_verification_gates.id", ondelete="CASCADE"), index=True)
    submitted_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    control_key: Mapped[str] = mapped_column(String(50))
    submission_version: Mapped[int] = mapped_column(Integer)
    implementation_summary: Mapped[str] = mapped_column(Text)
    verification_method: Mapped[str] = mapped_column(Text)
    rollback_plan: Mapped[str] = mapped_column(Text)
    owner_label: Mapped[str] = mapped_column(String(180))
    implementation_completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_reference: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="submitted", server_default="submitted")
    review_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

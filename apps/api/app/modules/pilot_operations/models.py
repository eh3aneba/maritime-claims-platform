from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
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

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values


class RequirementPriority(str, enum.Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    SUPPORTING = "supporting"


class RequirementStatus(str, enum.Enum):
    MISSING = "missing"
    REQUESTED = "requested"
    RECEIVED = "received"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    NOT_REQUIRED = "not_required"


class IssueCategory(str, enum.Enum):
    TECHNICAL = "technical"
    INSURANCE = "insurance"
    FINANCIAL = "financial"
    EVIDENCE = "evidence"
    OPERATIONAL = "operational"
    WORKFLOW = "workflow"


class IssueSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueStatus(str, enum.Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ClaimDocumentRequirement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_document_requirements"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "rule_id", "document_type", name="uq_claim_doc_req_rule_type"),
        Index("ix_claim_doc_req_org_claim_active", "organization_id", "claim_id", "is_active"),
        Index("ix_claim_doc_req_status", "organization_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    matched_document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    equivalent_claim_fact_id: Mapped[UUID | None] = mapped_column(ForeignKey("claim_facts.id", ondelete="SET NULL"), nullable=True)
    satisfied_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0", server_default="1.0")
    document_type: Mapped[str] = mapped_column(String(100), nullable=False)
    document_label: Mapped[str] = mapped_column(String(180), nullable=False)
    priority: Mapped[RequirementPriority] = mapped_column(
        Enum(RequirementPriority, name="requirement_priority", native_enum=True, values_callable=enum_values),
        nullable=False,
    )
    required_from_status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    satisfaction_basis: Mapped[str | None] = mapped_column(String(50), nullable=True)
    satisfaction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    satisfied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RequirementStatus] = mapped_column(
        Enum(RequirementStatus, name="requirement_status", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=RequirementStatus.MISSING,
        server_default=RequirementStatus.MISSING.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClaimIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_issues"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_id", "issue_key", name="uq_claim_issue_key"),
        Index("ix_claim_issues_org_claim_active", "organization_id", "claim_id", "is_active"),
        Index("ix_claim_issues_status", "organization_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)

    issue_key: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0", server_default="1.0")
    category: Mapped[IssueCategory] = mapped_column(
        Enum(IssueCategory, name="claim_issue_category", native_enum=True, values_callable=enum_values), nullable=False
    )
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[IssueSeverity] = mapped_column(
        Enum(IssueSeverity, name="claim_issue_severity", native_enum=True, values_callable=enum_values), nullable=False
    )
    status: Mapped[IssueStatus] = mapped_column(
        Enum(IssueStatus, name="claim_issue_status", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=IssueStatus.OPEN,
        server_default=IssueStatus.OPEN.value,
    )
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuleEvaluationRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rule_evaluation_runs"
    __table_args__ = (
        Index("ix_rule_runs_org_claim_created", "organization_id", "claim_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    evaluated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    ruleset_name: Mapped[str] = mapped_column(String(100), nullable=False, default="hm_machinery_rules", server_default="hm_machinery_rules")
    ruleset_version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0", server_default="1.0")
    trigger: Mapped[str] = mapped_column(String(50), nullable=False, default="manual", server_default="manual")
    triggered_rule_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

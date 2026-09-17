from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _EvidenceAdmissionAuthorizationSafetyMixin:
    upstream_checkpoint_generation_3_advance_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_generation_3_change_detection_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    latest_generation_3_observation_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    remote_version_current_at_authorization: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    human_authorization_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    provider_client_constructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_extracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    admission_execution_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    background_sync_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    always_true = (
        ("upstream_checkpoint_generation_3_advance_completed", "gen3"),
        ("upstream_generation_3_change_detection_completed", "change"),
        ("latest_generation_3_observation_confirmed", "latest"),
        ("remote_version_current_at_authorization", "current"),
        ("human_authorization_recorded", "human"),
    )
    always_false = (
        ("provider_client_constructed", "client"),
        ("remote_list_performed", "list"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("remote_delete_performed", "delete"),
        ("storage_read_performed", "storage_read"),
        ("storage_write_performed", "storage_write"),
        ("storage_delete_performed", "storage_delete"),
        ("document_created", "document"),
        ("evidence_admitted", "evidence"),
        ("content_parsed", "parsed"),
        ("content_extracted", "extracted"),
        ("claim_mutated", "claim"),
        ("admission_execution_performed", "execution"),
        ("background_sync_started", "background"),
    )
    return (
        *(CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in always_true),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in always_false),
    )


class ExternalDocumentSourceEvidenceAdmissionAuthorization(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _EvidenceAdmissionAuthorizationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_evidence_admission_auths"
    __table_args__ = (
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_eaa_request"),
        UniqueConstraint(
            "organization_id",
            "claim_id",
            "generation_3_change_detection_execution_id",
            name="uq_ext_doc_eaa_claim_observation",
        ),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_eaa_provider"),
        CheckConstraint("status = 'authorized'", name="ck_ext_doc_eaa_status"),
        CheckConstraint("authorized_byte_size IS NULL OR authorized_byte_size >= 0", name="ck_ext_doc_eaa_size"),
        Index("ix_ext_doc_eaa_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_eaa_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_eaa_observation", "generation_3_change_detection_execution_id"),
        *_safety_constraints("ext_doc_eaa"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    generation_3_change_detection_execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_doc_source_gen3_change_detect_execs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    checkpoint_generation_3_execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_doc_source_checkpoint_gen3_execs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_display_name_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authorized_byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    authorized_mime_type_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checkpoint_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_content_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="authorized", server_default="authorized")
    authorized_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    authorization_reason: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _EvidenceAdmissionAuthorizationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_evidence_admission_auth_receipts"
    __table_args__ = (
        UniqueConstraint("authorization_id", "sequence_number", name="uq_ext_doc_eaa_receipt_sequence"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_eaa_receipt_sequence"),
        CheckConstraint("event_type = 'authorized'", name="ck_ext_doc_eaa_receipt_event"),
        CheckConstraint("status_after = 'authorized'", name="ck_ext_doc_eaa_receipt_status"),
        CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_eaa_receipt_prior"),
        Index("ix_ext_doc_eaa_receipt_auth", "authorization_id"),
        *_safety_constraints("ext_doc_eaa_receipt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_doc_source_evidence_admission_auths.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False, default="authorized", server_default="authorized")
    status_after: Mapped[str] = mapped_column(String(24), nullable=False, default="authorized", server_default="authorized")
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)

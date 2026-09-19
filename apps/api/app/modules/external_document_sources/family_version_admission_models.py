from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _FamilyVersionAdmissionSafetyMixin:
    upstream_authorization_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    durable_family_binding_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    stable_source_identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    authorization_single_use_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    latest_generation_3_observation_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    fresh_exact_item_metadata_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    fresh_remote_version_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    staged_content_integrity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    malware_scan_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    canonical_document_write_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    new_document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    prior_document_superseded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    exactly_one_current_version_established: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    later_version_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    staged_storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    staged_storage_delete_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_extracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_advanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    background_sync_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    true_fields = (
        ("upstream_authorization_verified", "auth"),
        ("durable_family_binding_verified", "family"),
        ("stable_source_identity_verified", "source"),
        ("authorization_single_use_consumed", "single_use"),
        ("latest_generation_3_observation_confirmed", "latest"),
        ("fresh_exact_item_metadata_read_performed", "metadata"),
        ("fresh_remote_version_current", "current"),
        ("staged_content_integrity_verified", "staged"),
        ("malware_scan_completed", "malware"),
        ("canonical_document_write_completed", "canonical"),
        ("new_document_created", "new_doc"),
        ("prior_document_superseded", "superseded"),
        ("exactly_one_current_version_established", "one_current"),
        ("later_version_admitted", "admitted"),
    )
    false_fields = (
        ("remote_list_performed", "list"),
        ("remote_content_read_performed", "remote_content"),
        ("remote_write_performed", "remote_write"),
        ("remote_delete_performed", "remote_delete"),
        ("staged_storage_write_performed", "staged_write"),
        ("staged_storage_delete_performed", "staged_delete"),
        ("content_parsed", "parsed"),
        ("content_extracted", "extracted"),
        ("processing_enqueued", "processing"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("checkpoint_advanced", "checkpoint"),
        ("background_sync_started", "background"),
    )
    return (
        *(CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    )


class ExternalDocumentSourceFamilyVersionAdmissionExecution(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _FamilyVersionAdmissionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_family_version_admission_execs"
    __table_args__ = (
        UniqueConstraint("authorization_id", name="uq_ext_doc_fva_authorization"),
        UniqueConstraint("new_document_id", name="uq_ext_doc_fva_new_document"),
        UniqueConstraint("binding_id", "prior_document_id", name="uq_ext_doc_fva_prior"),
        UniqueConstraint("binding_id", "new_version_number", name="uq_ext_doc_fva_version"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_fva_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_fva_provider"),
        CheckConstraint("status = 'admitted'", name="ck_ext_doc_fva_status"),
        CheckConstraint("prior_version_number >= 1", name="ck_ext_doc_fva_prior_version"),
        CheckConstraint("new_version_number = prior_version_number + 1", name="ck_ext_doc_fva_next_version"),
        CheckConstraint("fresh_byte_size >= 0", name="ck_ext_doc_fva_fresh_size"),
        CheckConstraint("staged_content_byte_count >= 0", name="ck_ext_doc_fva_staged_size"),
        CheckConstraint("new_document_file_size_bytes >= 0", name="ck_ext_doc_fva_doc_size"),
        Index("ix_ext_doc_fva_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_fva_org_profile", "organization_id", "profile_id"),
        Index("ix_ext_doc_fva_binding", "binding_id"),
        Index("ix_ext_doc_fva_prior", "prior_document_id"),
        Index("ix_ext_doc_fva_new", "new_document_id"),
        *_safety_constraints("ext_doc_fva"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_admission_auths.id", ondelete="RESTRICT"), nullable=False)
    generation_3_change_detection_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_gen3_change_detect_execs.id", ondelete="RESTRICT"), nullable=False)
    checkpoint_generation_3_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_checkpoint_gen3_execs.id", ondelete="RESTRICT"), nullable=False)
    successor_versioned_restaging_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_successor_versioned_restage_execs.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    prior_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    prior_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    new_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    new_version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_content_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_provider_version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prior_document_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    fresh_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fresh_display_name_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fresh_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fresh_byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fresh_mime_type_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    staged_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    staged_content_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    staged_storage_object_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    new_document_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    new_document_file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_document_filename_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_storage_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="admitted", server_default="admitted")
    executed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    execution_reason: Mapped[str] = mapped_column(Text, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceFamilyVersionAdmissionReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _FamilyVersionAdmissionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_family_version_admission_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_fva_rcpt_seq"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_fva_rcpt_seq"),
        CheckConstraint("event_type = 'admitted'", name="ck_ext_doc_fva_rcpt_event"),
        CheckConstraint("status_after = 'admitted'", name="ck_ext_doc_fva_rcpt_status"),
        CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_fva_rcpt_prior"),
        Index("ix_ext_doc_fva_rcpt_execution", "execution_id"),
        *_safety_constraints("ext_doc_fva_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_family_version_admission_execs.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False, default="admitted", server_default="admitted")
    status_after: Mapped[str] = mapped_column(String(24), nullable=False, default="admitted", server_default="admitted")
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)

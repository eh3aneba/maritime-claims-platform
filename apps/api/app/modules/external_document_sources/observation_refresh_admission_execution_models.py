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
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


def _execution_safety_constraints(prefix: str):
    true_fields = (
        ("authorization_verified", "auth"),
        ("refresh_execution_verified", "refresh"),
        ("durable_family_binding_verified", "family"),
        ("stable_source_identity_verified", "source"),
        ("authorization_single_use_consumed", "single_use"),
        ("current_document_verified", "current"),
        ("staged_storage_read_performed", "staged_read"),
        ("staged_content_integrity_verified", "staged"),
        ("file_signature_validated", "signature"),
        ("malware_scan_completed", "malware"),
        ("canonical_document_write_completed", "canonical"),
        ("new_document_created", "new_doc"),
        ("prior_document_superseded", "superseded"),
        ("exactly_one_current_version_established", "one_current"),
        ("refreshed_version_admitted", "admitted"),
    )
    false_fields = (
        ("provider_client_constructed", "client"),
        ("oauth_token_acquired", "oauth"),
        ("remote_list_performed", "list"),
        ("remote_metadata_read_performed", "metadata"),
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


class _ObservationRefreshAdmissionExecutionSafetyMixin:
    authorization_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    refresh_execution_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    durable_family_binding_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    stable_source_identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    authorization_single_use_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    current_document_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    staged_storage_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    staged_content_integrity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    file_signature_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    malware_scan_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    canonical_document_write_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    new_document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    prior_document_superseded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    exactly_one_current_version_established: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    refreshed_version_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    provider_client_constructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    oauth_token_acquired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_metadata_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
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


class ExternalDocumentSourceObservationRefreshAdmissionExecution(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ObservationRefreshAdmissionExecutionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_observation_refresh_admission_execs"
    __table_args__ = (
        UniqueConstraint("authorization_id", name="uq_ext_doc_obs_refresh_adm_exec_auth"),
        UniqueConstraint("new_document_id", name="uq_ext_doc_obs_refresh_adm_exec_new_doc"),
        UniqueConstraint("binding_id", "prior_document_id", name="uq_ext_doc_obs_refresh_adm_exec_prior"),
        UniqueConstraint("binding_id", "new_version_number", name="uq_ext_doc_obs_refresh_adm_exec_version"),
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_ext_doc_obs_refresh_adm_exec_request"),
        CheckConstraint("provider_kind IN ('sharepoint','google_drive')", name="ck_ext_doc_obs_refresh_adm_exec_provider"),
        CheckConstraint("status = 'admitted'", name="ck_ext_doc_obs_refresh_adm_exec_status"),
        CheckConstraint("prior_version_number >= 1", name="ck_ext_doc_obs_refresh_adm_exec_prior_ver"),
        CheckConstraint("new_version_number = prior_version_number + 1", name="ck_ext_doc_obs_refresh_adm_exec_next_ver"),
        CheckConstraint("refreshed_content_byte_count >= 0", name="ck_ext_doc_obs_refresh_adm_exec_size"),
        CheckConstraint("new_document_file_size_bytes >= 0", name="ck_ext_doc_obs_refresh_adm_exec_doc_size"),
        CheckConstraint("malware_scan_verdict = 'clean'", name="ck_ext_doc_obs_refresh_adm_exec_malware"),
        Index("ix_ext_doc_obs_refresh_adm_exec_org_claim", "organization_id", "claim_id"),
        Index("ix_ext_doc_obs_refresh_adm_exec_binding", "binding_id"),
        *_execution_safety_constraints("ext_doc_obs_refresh_adm_exec"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_evidence_family_bindings.id", ondelete="RESTRICT"), nullable=False)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_refresh_admission_auths.id", ondelete="RESTRICT"), nullable=False)
    refresh_execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_refresh_execs.id", ondelete="RESTRICT"), nullable=False)
    document_family_id: Mapped[UUID] = mapped_column(nullable=False)
    prior_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    prior_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    new_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    new_version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    refresh_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_document_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    refreshed_content_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    refreshed_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    refreshed_content_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refreshed_content_media_type_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    refreshed_content_version_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    staged_storage_backend_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    staged_storage_purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    staged_storage_object_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    validated_file_suffix: Mapped[str] = mapped_column(String(16), nullable=False)
    malware_scan_verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    security_verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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


class ExternalDocumentSourceObservationRefreshAdmissionReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _ObservationRefreshAdmissionExecutionSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_observation_refresh_admission_receipts"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence_number", name="uq_ext_doc_obs_refresh_adm_exec_rcpt_seq"),
        CheckConstraint("sequence_number = 1", name="ck_ext_doc_obs_refresh_adm_exec_rcpt_seq"),
        CheckConstraint("event_type = 'admitted'", name="ck_ext_doc_obs_refresh_adm_exec_rcpt_event"),
        CheckConstraint("status_after = 'admitted'", name="ck_ext_doc_obs_refresh_adm_exec_rcpt_status"),
        CheckConstraint("prior_receipt_hash IS NULL", name="ck_ext_doc_obs_refresh_adm_exec_rcpt_prior"),
        *_execution_safety_constraints("ext_doc_obs_refresh_adm_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_observation_refresh_admission_execs.id", ondelete="RESTRICT"), nullable=False)
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

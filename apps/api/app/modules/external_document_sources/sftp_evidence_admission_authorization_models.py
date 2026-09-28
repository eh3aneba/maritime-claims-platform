from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class _SftpEvidenceAdmissionAuthorizationSafetyMixin:
    upstream_generation3_checkpoint_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    upstream_generation3_observation_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    latest_generation3_observation_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    remote_version_current_at_authorization: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    human_authorization_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    credential_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    session_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    provider_network_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ssh_transport_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    authentication_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    sftp_session_opened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_content_transiently_observed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_list_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_stat_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    remote_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_read_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_write_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    storage_reconciliation_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    durable_content_staged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    checkpoint_advanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    document_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    evidence_admitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    content_extracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    processing_enqueued: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    ai_executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    claim_mutated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    background_sync_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


def _safety_constraints(prefix: str):
    true_fields = (
        ("upstream_generation3_checkpoint_completed", "q"),
        ("upstream_generation3_observation_completed", "r"),
        ("latest_generation3_observation_confirmed", "latest"),
        ("remote_version_current_at_authorization", "current"),
        ("human_authorization_recorded", "human"),
    )
    false_fields = (
        ("credential_stored", "cred"),
        ("session_stored", "sess"),
        ("provider_network_performed", "net"),
        ("ssh_transport_performed", "ssh"),
        ("authentication_performed", "auth"),
        ("sftp_session_opened", "sftp"),
        ("remote_content_transiently_observed", "content"),
        ("remote_list_performed", "list"),
        ("remote_stat_performed", "stat"),
        ("remote_read_performed", "read"),
        ("remote_write_performed", "write"),
        ("storage_read_performed", "sread"),
        ("storage_write_performed", "swrite"),
        ("storage_reconciliation_performed", "srecon"),
        ("durable_content_staged", "stage"),
        ("checkpoint_created", "cpcreate"),
        ("checkpoint_advanced", "cpadvance"),
        ("document_created", "doc"),
        ("evidence_admitted", "evidence"),
        ("content_parsed", "parsed"),
        ("content_extracted", "extract"),
        ("processing_enqueued", "process"),
        ("ai_executed", "ai"),
        ("claim_mutated", "claim"),
        ("background_sync_started", "bg"),
    )
    return (
        *(CheckConstraint(f"{field} = true", name=f"ck_{prefix}_{suffix}") for field, suffix in true_fields),
        *(CheckConstraint(f"{field} = false", name=f"ck_{prefix}_no_{suffix}") for field, suffix in false_fields),
    )


class ExternalDocumentSourceSftpEvidenceAdmissionAuthorization(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpEvidenceAdmissionAuthorizationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_evidence_admission_auths"
    __table_args__ = (
        UniqueConstraint("organization_id", "profile_id", "request_key", name="uq_sftp_eaa_request"),
        UniqueConstraint("organization_id", "claim_id", "generation3_change_detection_id", name="uq_sftp_eaa_claim_obs"),
        CheckConstraint("provider_kind = 'sftp'", name="ck_sftp_eaa_provider"),
        CheckConstraint("status = 'authorized'", name="ck_sftp_eaa_status"),
        CheckConstraint("authorized_byte_size >= 0", name="ck_sftp_eaa_size"),
        Index("ix_sftp_eaa_org_claim", "organization_id", "claim_id"),
        Index("ix_sftp_eaa_org_profile", "organization_id", "profile_id"),
        Index("ix_sftp_eaa_observation", "generation3_change_detection_id"),
        *_safety_constraints("sftp_eaa"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("external_document_source_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    generation3_change_detection_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_generation3_change_detections.id", ondelete="RESTRICT"), nullable=False, index=True)
    generation3_checkpoint_advancement_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_generation3_checkpoint_advancements.id", ondelete="RESTRICT"), nullable=False, index=True)
    generation3_restaging_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_generation3_restaging.id", ondelete="RESTRICT"), nullable=False, index=True)

    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_relative_path_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authorized_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorized_metadata_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authorized_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_storage_object_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_purpose: Mapped[str] = mapped_column(String(128), nullable=False)

    checkpoint_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_content_proof_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_completion_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="authorized", server_default="authorized")
    authorized_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_reason: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    _SftpEvidenceAdmissionAuthorizationSafetyMixin,
    Base,
):
    __tablename__ = "external_doc_source_sftp_evidence_admission_auth_receipts"
    __table_args__ = (
        UniqueConstraint("authorization_id", "sequence_number", name="uq_sftp_eaa_rcpt_seq"),
        UniqueConstraint("organization_id", "receipt_hash", name="uq_sftp_eaa_rcpt_hash"),
        CheckConstraint("sequence_number = 1", name="ck_sftp_eaa_rcpt_seq"),
        CheckConstraint("event_type = 'authorized'", name="ck_sftp_eaa_rcpt_event"),
        CheckConstraint("status_after = 'authorized'", name="ck_sftp_eaa_rcpt_status"),
        CheckConstraint("prior_receipt_hash IS NULL", name="ck_sftp_eaa_rcpt_prior"),
        Index("ix_sftp_eaa_rcpt_auth", "authorization_id"),
        *_safety_constraints("sftp_eaa_rcpt"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    authorization_id: Mapped[UUID] = mapped_column(ForeignKey("external_doc_source_sftp_evidence_admission_auths.id", ondelete="RESTRICT"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False, default="authorized", server_default="authorized")
    status_after: Mapped[str] = mapped_column(String(24), nullable=False, default="authorized", server_default="authorized")
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)

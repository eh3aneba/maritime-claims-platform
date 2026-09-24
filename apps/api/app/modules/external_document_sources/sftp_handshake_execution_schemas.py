from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceSftpHandshakeExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceSftpHandshakeExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    authorization_id: UUID
    health_qualification_id: UUID
    credential_reference_binding_id: UUID
    provider_kind: str
    profile_hash: str
    binding_scope_hash: str
    binding_request_hash: str
    binding_approval_hash: str
    locator_hash: str
    authentication_kind: str
    reference_backend: str
    resolver_kind: str
    health_scope_hash: str
    health_request_hash: str
    health_result_hash: str
    health_result_status: str
    handshake_authorization_scope_hash: str
    handshake_authorization_request_hash: str
    handshake_authorization_hash: str
    handshake_authorization_expires_at: datetime
    execution_limit: int
    request_key: str
    scope_hash: str
    request_hash: str
    status: str
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    authorization_terminal_hash: str | None
    completed_at: datetime | None
    completion_hash: str | None
    credential_reference_stored: bool
    secret_resolution_performed: bool
    credential_stored: bool
    provider_network_performed: bool
    authentication_performed: bool
    sftp_session_opened: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    evidence_admitted: bool
    document_created: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    sftp_handshake_authorized: bool
    handshake_authorization_consumed: bool

    @field_serializer(
        "handshake_authorization_expires_at",
        "requested_at",
        "completed_at",
    )
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceSftpHandshakeExecutionReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    execution_id: UUID
    sequence_number: int
    event_type: str
    status_after: str
    actor_id: UUID
    occurred_at: datetime
    reason: str
    scope_hash: str
    decision_hash: str
    prior_receipt_hash: str | None
    receipt_hash: str
    credential_reference_stored: bool
    secret_resolution_performed: bool
    credential_stored: bool
    provider_network_performed: bool
    authentication_performed: bool
    sftp_session_opened: bool
    remote_list_performed: bool
    remote_read_performed: bool
    remote_write_performed: bool
    remote_delete_performed: bool
    evidence_admitted: bool
    document_created: bool
    processing_enqueued: bool
    ai_executed: bool
    claim_mutated: bool
    sftp_handshake_authorized: bool
    handshake_authorization_consumed: bool

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

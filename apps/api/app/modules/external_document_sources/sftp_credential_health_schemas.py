from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExternalDocumentSourceSftpCredentialHealthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=2000)


class ExternalDocumentSourceSftpCredentialHealthRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
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
    request_key: str
    scope_hash: str
    request_hash: str
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    checked_at: datetime
    result_status: str
    failure_code: str | None
    resolved_material_kind: str | None
    result_hash: str
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

    @field_serializer("requested_at", "checked_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class ExternalDocumentSourceSftpCredentialHealthReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    qualification_id: UUID
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

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

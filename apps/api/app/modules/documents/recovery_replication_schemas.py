from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryReplicationRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class RecoveryReplicaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    source_file_hash: str
    source_file_size_bytes: int
    source_document_updated_at: datetime
    source_storage_key_fingerprint: str
    recovery_storage_key: str
    recovery_bucket_fingerprint: str
    remote_etag: str | None
    replica_hash: str
    request_reason: str
    replicated_by_id: UUID
    replicated_at: datetime
    verified_at: datetime
    created_at: datetime
    updated_at: datetime


class RecoveryVerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    replica_id: UUID
    expected_file_hash: str
    expected_file_size_bytes: int
    observed_file_hash: str
    observed_file_size_bytes: int
    recovery_bucket_fingerprint: str
    remote_etag: str | None
    verification_reason: str
    verification_hash: str
    verified_by_id: UUID
    verified_at: datetime
    created_at: datetime
    updated_at: datetime


class RecoveryReplicationOperationRead(BaseModel):
    replica: RecoveryReplicaRead
    verification: RecoveryVerificationRead
    created: bool

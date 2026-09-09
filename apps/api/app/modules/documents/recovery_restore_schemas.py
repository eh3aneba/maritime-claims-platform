from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryRestoreRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class RecoveryRestoreRehearsalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    replica_id: UUID
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    source_document_updated_at: datetime
    source_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    recovery_storage_key_fingerprint: str
    staging_storage_key_fingerprint: str
    restored_file_hash: str
    restored_file_size_bytes: int
    remote_etag: str | None
    rehearsal_hash: str
    request_reason: str
    restored_by_id: UUID
    restored_at: datetime
    verified_at: datetime
    created_at: datetime
    updated_at: datetime


class RecoveryRestoreVerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    replica_id: UUID
    rehearsal_id: UUID
    expected_file_hash: str
    expected_file_size_bytes: int
    remote_file_hash: str
    remote_file_size_bytes: int
    staged_file_hash: str
    staged_file_size_bytes: int
    recovery_bucket_fingerprint: str
    staging_storage_key_fingerprint: str
    remote_etag: str | None
    verification_reason: str
    verification_hash: str
    verified_by_id: UUID
    verified_at: datetime
    created_at: datetime
    updated_at: datetime


class RecoveryRestoreOperationRead(BaseModel):
    rehearsal: RecoveryRestoreRehearsalRead
    verification: RecoveryRestoreVerificationRead
    created: bool

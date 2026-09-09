from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryShadowRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryShadowPromotionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    attestation_id: UUID
    replica_id: UUID
    rehearsal_id: UUID
    restore_verification_id: UUID
    attestation_request_snapshot_hash: str
    promotion_plan_hash: str
    configuration_fingerprint: str
    replica_hash: str
    rehearsal_hash: str
    restore_verification_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    source_document_updated_at: datetime
    source_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    recovery_storage_key_fingerprint: str
    staging_storage_key_fingerprint: str
    shadow_storage_key_fingerprint: str
    shadow_file_hash: str
    shadow_file_size_bytes: int
    shadow_promotion_hash: str
    rehearsal_reason: str
    promoted_by_id: UUID
    promoted_at: datetime
    verified_at: datetime
    created_at: datetime
    updated_at: datetime


class RecoveryShadowVerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    attestation_id: UUID
    shadow_promotion_id: UUID
    expected_file_hash: str
    expected_file_size_bytes: int
    shadow_file_hash: str
    shadow_file_size_bytes: int
    promotion_plan_hash: str
    configuration_fingerprint: str
    shadow_storage_key_fingerprint: str
    verification_reason: str
    verification_hash: str
    verified_by_id: UUID
    verified_at: datetime
    created_at: datetime
    updated_at: datetime


class RecoveryShadowOperationRead(BaseModel):
    rehearsal: RecoveryShadowPromotionRead
    verification: RecoveryShadowVerificationRead
    created: bool

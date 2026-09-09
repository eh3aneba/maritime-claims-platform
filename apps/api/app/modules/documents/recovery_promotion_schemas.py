from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryPromotionRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryPromotionDecision(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryPromotionAttestationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    replica_id: UUID
    rehearsal_id: UUID
    restore_verification_id: UUID
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
    configuration_fingerprint: str
    promotion_plan: dict
    promotion_plan_hash: str
    request_snapshot_hash: str
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    attestation_expires_at: datetime
    status: str
    approved_by_id: UUID | None
    approved_at: datetime | None
    rejected_by_id: UUID | None
    rejected_at: datetime | None
    invalidated_by_id: UUID | None
    invalidated_at: datetime | None
    decision_reason: str | None
    cutover_performed: bool
    authoritative_storage_changed: bool
    created_at: datetime
    updated_at: datetime

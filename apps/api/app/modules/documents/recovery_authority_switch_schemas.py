from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryAuthoritySwitchReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryAuthoritySwitchRehearsalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    shadow_promotion_id: UUID
    attestation_id: UUID
    replica_id: UUID
    restore_rehearsal_id: UUID
    restore_verification_id: UUID
    shadow_verification_id: UUID
    attestation_request_snapshot_hash: str
    promotion_plan_hash: str
    configuration_fingerprint: str
    shadow_promotion_hash: str
    shadow_verification_hash: str
    source_file_hash: str
    source_storage_key_fingerprint: str
    shadow_storage_key_fingerprint: str
    lineage_hash: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    contract_hash: str
    status: str
    virtual_authority_class: str
    virtual_authority_fingerprint: str
    activation_lease_expires_at: datetime
    prepared_by_id: UUID
    prepared_at: datetime
    preparation_reason: str
    activated_by_id: UUID | None
    activated_at: datetime | None
    activation_reason: str | None
    rolled_back_by_id: UUID | None
    rolled_back_at: datetime | None
    rollback_reason: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    cutover_performed: bool
    authoritative_storage_changed: bool
    document_storage_key_mutated: bool
    active_backend_changed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryAuthoritySwitchReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authority_switch_rehearsal_id: UUID
    shadow_promotion_id: UUID
    phase: str
    from_authority_class: str
    to_authority_class: str
    from_authority_fingerprint: str
    to_authority_fingerprint: str
    lineage_hash: str
    contract_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    cutover_performed: bool
    authoritative_storage_changed: bool
    created_at: datetime
    updated_at: datetime


class RecoveryAuthoritySwitchOperationRead(BaseModel):
    rehearsal: RecoveryAuthoritySwitchRehearsalRead
    receipt: RecoveryAuthoritySwitchReceiptRead | None
    outcome: str

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecoveryCutoverAdmissionReason(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class RecoveryCutoverAdmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    authority_switch_rehearsal_id: UUID
    activation_receipt_id: UUID
    rollback_receipt_id: UUID
    shadow_promotion_id: UUID
    attestation_id: UUID
    replica_id: UUID
    restore_rehearsal_id: UUID
    restore_verification_id: UUID
    shadow_verification_id: UUID
    rehearsal_contract_hash: str
    rehearsal_lineage_hash: str
    activation_receipt_hash: str
    rollback_receipt_hash: str
    transition_proof_hash: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    request_snapshot_hash: str
    admission_hash: str
    status: str
    admission_expires_at: datetime
    requested_by_id: UUID
    requested_at: datetime
    request_reason: str
    approved_by_id: UUID | None
    approved_at: datetime | None
    approval_reason: str | None
    rejected_by_id: UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    cutover_performed: bool
    authoritative_storage_changed: bool
    document_storage_key_mutated: bool
    active_backend_changed: bool
    production_execution_token_created: bool
    execution_authority_created: bool
    created_at: datetime
    updated_at: datetime


class RecoveryCutoverAdmissionReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    document_id: UUID
    cutover_admission_id: UUID
    authority_switch_rehearsal_id: UUID
    phase: str
    request_snapshot_hash: str
    admission_hash: str
    transition_proof_hash: str
    receipt_hash: str
    actor_id: UUID
    reason: str
    transitioned_at: datetime
    execution_authority_created: bool
    created_at: datetime
    updated_at: datetime


class RecoveryCutoverAdmissionOperationRead(BaseModel):
    admission: RecoveryCutoverAdmissionRead
    receipt: RecoveryCutoverAdmissionReceiptRead | None
    outcome: str

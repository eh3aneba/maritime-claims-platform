from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DisposalAuthorizationRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=4000)


class DisposalAuthorizationDecision(BaseModel):
    reason: str = Field(min_length=8, max_length=4000)


class DisposalAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    retention_policy_id: UUID
    retention_policy_number: int
    retention_policy_hash: str
    claim_retention_anchor_at: datetime
    claim_retention_expires_at: datetime
    evidence_retention_anchor_at: datetime
    evidence_retention_expires_at: datetime
    eligibility_evaluated_at: datetime
    eligibility_snapshot_hash: str
    state_fingerprint: str
    active_hold_ids: list[str]
    pending_proposal_ids: list[str]
    requested_by_id: UUID
    request_reason: str
    authorization_expires_at: datetime
    status: str
    approved_by_id: UUID | None
    approved_at: datetime | None
    rejected_by_id: UUID | None
    rejected_at: datetime | None
    invalidated_by_id: UUID | None
    invalidated_at: datetime | None
    decision_reason: str | None
    created_at: datetime
    updated_at: datetime

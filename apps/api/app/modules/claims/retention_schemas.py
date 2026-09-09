from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RetentionPolicyCreate(BaseModel):
    closed_claim_retention_days: int = Field(ge=30, le=36500)
    evidence_retention_days: int = Field(ge=30, le=36500)
    enabled: bool = True
    disposal_enabled: bool = False


class RetentionPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    policy_number: int
    closed_claim_retention_days: int
    evidence_retention_days: int
    enabled: bool
    disposal_enabled: bool
    policy_hash: str
    previous_policy_hash: str | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class LegalHoldCreate(BaseModel):
    source: Literal["manual", "litigation", "regulatory", "investigation"] = "manual"
    reason: str = Field(min_length=3, max_length=4000)


class LegalHoldRelease(BaseModel):
    reason: str = Field(min_length=3, max_length=4000)


class LegalHoldRead(BaseModel):
    id: UUID
    organization_id: UUID
    claim_id: UUID
    source: str
    reason: str
    placed_by_id: UUID
    released_at: datetime | None
    released_by_id: UUID | None
    release_reason: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DisposalEligibilityRead(BaseModel):
    claim_id: UUID
    policy_id: UUID | None
    policy_number: int | None
    eligible: bool
    blocking_reasons: list[str]
    active_hold_ids: list[UUID]
    retention_anchor_at: datetime
    claim_retention_expires_at: datetime | None
    evidence_retention_expires_at: datetime | None
    earliest_eligible_at: datetime | None
    evaluated_at: datetime

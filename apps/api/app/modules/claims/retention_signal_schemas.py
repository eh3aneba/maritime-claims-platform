from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


HoldSource = Literal["litigation", "regulatory", "investigation"]


class PreservationSignalProfileCreate(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    enabled: bool = False
    allowed_hold_sources: list[HoldSource] = Field(min_length=1, max_length=3)


class PreservationSignalProfileUpdate(BaseModel):
    enabled: bool | None = None
    allowed_hold_sources: list[HoldSource] | None = Field(default=None, min_length=1, max_length=3)


class PreservationSignalProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    enabled: bool
    allowed_hold_sources: list[str]
    secret_version: int
    secret_reference: str
    previous_secret_version: int | None
    previous_secret_valid_until: datetime | None
    rotated_at: datetime | None
    created_by_id: UUID
    updated_by_id: UUID
    created_at: datetime
    updated_at: datetime


class PreservationSignalProfileSecretRead(BaseModel):
    profile: PreservationSignalProfileRead
    signing_secret: str


class PreservationSignalPayload(BaseModel):
    claim_id: UUID
    recommended_hold_source: HoldSource
    reason: str = Field(min_length=3, max_length=4000)
    event_type: str = Field(min_length=3, max_length=120)


class PreservationSignalReceipt(BaseModel):
    proposal_id: UUID
    claim_id: UUID
    proposal_status: str
    created: bool
    source_kind: str
    source_ref_fingerprint: str
    source_payload_hash: str

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScimProvisioningProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_name: str = Field(min_length=1, max_length=160)
    token_ttl_days: int = Field(default=30, ge=1, le=90)
    enabled: bool = False

    @field_validator("client_name")
    @classmethod
    def client_name_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("SCIM provisioning client name must not be blank")
        return normalized


class ScimProvisioningProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_number: int
    client_name: str
    service_base_path: str
    token_ttl_days: int
    enabled: bool
    profile_hash: str
    previous_profile_hash: str | None
    created_by_id: UUID
    created_at: datetime


class ScimProvisioningTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_id: UUID
    profile_number: int
    profile_hash: str
    token_prefix: str
    expires_at: datetime
    revoked_at: datetime | None
    revoked_by_id: UUID | None
    revocation_reason: str | None
    created_by_id: UUID
    created_at: datetime


class ScimProvisioningTokenIssued(BaseModel):
    token: str
    credential: ScimProvisioningTokenRead

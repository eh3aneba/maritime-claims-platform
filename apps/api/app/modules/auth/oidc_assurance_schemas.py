from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OidcMfaAssuranceProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    accepted_amr_values: list[str] = Field(default_factory=list, max_length=20)
    accepted_acr_values: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("accepted_amr_values", "accepted_acr_values")
    @classmethod
    def values_must_be_unique_and_nonblank(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("OIDC assurance values must not be blank")
        if len(stripped) != len(set(stripped)):
            raise ValueError("OIDC assurance values must be unique")
        return stripped


class OidcMfaAssuranceProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    provider_id: UUID
    trust_profile_id: UUID
    trust_profile_number: int
    trust_profile_hash: str
    profile_number: int
    enabled: bool
    accepted_amr_values: list[str]
    accepted_acr_values: list[str]
    profile_hash: str
    previous_profile_hash: str | None
    created_by_id: UUID
    created_at: datetime

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SamlMfaAssuranceProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    accepted_authn_context_values: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("accepted_authn_context_values")
    @classmethod
    def values_must_be_unique_and_bounded(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("SAML AuthnContext values must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("SAML AuthnContext values must be unique")
        if any(len(item) > 512 for item in normalized):
            raise ValueError("SAML AuthnContext value is too long")
        return normalized


class SamlMfaAssuranceProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    provider_id: UUID
    saml_profile_id: UUID
    saml_profile_number: int
    saml_profile_hash: str
    profile_number: int
    enabled: bool
    accepted_authn_context_values: list[str]
    profile_hash: str
    previous_profile_hash: str | None
    created_by_id: UUID
    created_at: datetime

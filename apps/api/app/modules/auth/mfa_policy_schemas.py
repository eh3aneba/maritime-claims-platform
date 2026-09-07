from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MfaPolicyRole = Literal["admin", "claims_manager", "claims_handler"]


class MfaPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_enabled: bool
    required_roles: list[MfaPolicyRole] = Field(default_factory=list, max_length=3)

    @field_validator("required_roles")
    @classmethod
    def required_roles_must_be_unique(
        cls,
        value: list[MfaPolicyRole],
    ) -> list[MfaPolicyRole]:
        if len(value) != len(set(value)):
            raise ValueError("MFA policy roles must be unique")
        return value


class MfaPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: UUID
    is_enabled: bool
    required_roles: list[str]
    updated_by_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

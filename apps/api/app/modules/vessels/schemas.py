from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VesselCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    imo_number: str | None = Field(default=None, min_length=7, max_length=7)
    vessel_type: str | None = Field(default=None, max_length=100)
    flag: str | None = Field(default=None, max_length=100)
    class_society: str | None = Field(default=None, max_length=150)
    year_built: int | None = Field(default=None, ge=1800, le=2200)
    deadweight: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    owner: str | None = Field(default=None, max_length=200)
    manager: str | None = Field(default=None, max_length=200)

    @field_validator("imo_number")
    @classmethod
    def normalize_imo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized.isdigit():
            raise ValueError("IMO number must contain seven digits")
        return normalized


class VesselRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    imo_number: str | None
    vessel_type: str | None
    flag: str | None
    class_society: str | None
    year_built: int | None
    deadweight: Decimal | None
    owner: str | None
    manager: str | None


class VesselListResponse(BaseModel):
    items: list[VesselRead]
    total: int

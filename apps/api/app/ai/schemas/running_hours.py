from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_index: int | None
    quote: str | None


class SourcedString(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str | None
    confidence: float = Field(ge=0, le=1)
    source: EvidenceRef


class SourcedBoolean(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: bool | None
    confidence: float = Field(ge=0, le=1)
    source: EvidenceRef


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: Literal["running_hours_record", "other", "unknown"]
    confidence: float = Field(ge=0, le=1)


class RunningHoursExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Classification
    vessel_name: SourcedString
    imo_number: SourcedString
    equipment_name: SourcedString
    equipment_maker: SourcedString
    equipment_model: SourcedString
    equipment_serial_number: SourcedString
    total_running_hours: SourcedString
    running_hours_since_overhaul: SourcedString
    last_overhaul_date: SourcedString
    recommended_overhaul_interval: SourcedString
    interval_extension_approved: SourcedBoolean
    interval_extension_details: SourcedString

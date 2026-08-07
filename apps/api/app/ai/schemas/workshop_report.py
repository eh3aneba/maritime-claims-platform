from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    document_type: Literal["workshop_report", "other", "unknown"]
    confidence: float = Field(ge=0, le=1)


class DamageFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: SourcedString
    description: SourcedString
    extent: SourcedString
    measurement: SourcedString

    @model_validator(mode="after")
    def meaningful(self):
        if not any(v.value is not None for v in [self.component, self.description, self.extent, self.measurement]):
            raise ValueError("Damage findings must contain supported evidence.")
        return self


class RepairOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: SourcedString
    repair_or_replace: SourcedString
    duration: SourcedString
    parts_required: SourcedString
    lead_time: SourcedString


class WorkshopReportExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Classification
    workshop_name: SourcedString
    attendance_date: SourcedString
    vessel_name: SourcedString
    equipment_name: SourcedString
    equipment_maker: SourcedString
    equipment_model: SourcedString
    equipment_serial_number: SourcedString
    repairable: SourcedBoolean
    temporary_repair: SourcedBoolean
    damage_findings: list[DamageFinding]
    repair_options: list[RepairOption]
    suspected_cause_opinions: list[SourcedString]
    recommendations: list[SourcedString]

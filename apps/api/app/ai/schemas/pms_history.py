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
    document_type: Literal["pms_history", "other", "unknown"]
    confidence: float = Field(ge=0, le=1)


class PMSRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_code: SourcedString
    task: SourcedString
    scheduled_date: SourcedString
    completed_date: SourcedString
    scheduled_running_hours: SourcedString
    actual_running_hours: SourcedString
    status: SourcedString
    deferred: SourcedBoolean
    overdue: SourcedBoolean
    remarks: SourcedString

    @model_validator(mode="after")
    def meaningful(self):
        values = [self.job_code.value, self.task.value, self.scheduled_date.value, self.completed_date.value,
                  self.scheduled_running_hours.value, self.actual_running_hours.value, self.status.value,
                  self.deferred.value, self.overdue.value, self.remarks.value]
        if not any(value is not None for value in values):
            raise ValueError("PMS records must contain at least one supported value.")
        return self


class PMSHistoryExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Classification
    vessel_name: SourcedString
    imo_number: SourcedString
    equipment_name: SourcedString
    overall_status: SourcedString
    overhaul_deferred: SourcedBoolean
    running_hours_since_overhaul: SourcedString
    last_overhaul_date: SourcedString
    records: list[PMSRecord]

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
    document_type: Literal["engine_log", "other", "unknown"]
    confidence: float = Field(ge=0, le=1)


class Identification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vessel_name: SourcedString
    imo_number: SourcedString
    log_date: SourcedString
    engine_or_equipment: SourcedString


class EngineLogEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: SourcedString
    time: SourcedString
    timezone: SourcedString
    event_type: SourcedString
    rpm: SourcedString
    engine_load: SourcedString
    turbocharger_speed: SourcedString
    exhaust_temperature: SourcedString
    lube_oil_pressure: SourcedString
    alarm: SourcedString
    shutdown: SourcedBoolean
    restart: SourcedBoolean
    action: SourcedString
    remarks: SourcedString

    @model_validator(mode="after")
    def require_meaningful_event(self):
        values = [
            self.date.value,
            self.time.value,
            self.event_type.value,
            self.rpm.value,
            self.engine_load.value,
            self.turbocharger_speed.value,
            self.exhaust_temperature.value,
            self.lube_oil_pressure.value,
            self.alarm.value,
            self.shutdown.value,
            self.restart.value,
            self.action.value,
            self.remarks.value,
        ]
        if not any(value is not None for value in values):
            raise ValueError("Engine-log event rows must contain at least one supported value.")
        return self


class EngineLogExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Classification
    identification: Identification
    events: list[EngineLogEvent]

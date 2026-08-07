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
    document_type: Literal["chief_engineer_report", "other", "unknown"]
    confidence: float = Field(ge=0, le=1)


class Identification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vessel_name: SourcedString
    imo_number: SourcedString
    report_date: SourcedString
    author_name: SourcedString
    author_rank: SourcedString


class Incident(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: SourcedString
    time: SourcedString
    timezone: SourcedString
    location: SourcedString
    voyage_from: SourcedString
    voyage_to: SourcedString
    cargo_status: SourcedString
    first_observation: SourcedString


class Equipment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    equipment_type: SourcedString
    equipment_name: SourcedString
    maker: SourcedString
    model: SourcedString
    serial_number: SourcedString


class OperationalImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine_stopped: SourcedBoolean
    load_reduced: SourcedBoolean
    speed_reduced: SourcedBoolean
    immobilized: SourcedBoolean
    deviation: SourcedBoolean
    towage: SourcedBoolean


class ReportedEvent(BaseModel):
    """One narrative event exactly as reported by the Chief Engineer.

    Date/time fields are intentionally independent per event. A null time means the
    source did not state a usable clock time for that event; callers must not copy the
    incident start time into it.
    """

    model_config = ConfigDict(extra="forbid")
    date: SourcedString
    time: SourcedString
    timezone: SourcedString
    event_type: SourcedString
    description: SourcedString


class ChiefEngineerReportExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Classification
    identification: Identification
    incident: Incident
    equipment: Equipment
    symptoms: list[SourcedString]
    immediate_actions: list[SourcedString]
    reported_events: list[ReportedEvent]
    operational_impact: OperationalImpact
    suspected_cause_opinions: list[SourcedString]
    recommendations: list[SourcedString]

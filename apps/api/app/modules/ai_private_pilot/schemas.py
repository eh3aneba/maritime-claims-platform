from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


PilotDocumentType = Literal["chief_engineer_report", "engine_log"]


class AIPrivatePilotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation_suite_id: UUID
    pilot_key: str = Field(min_length=8, max_length=120)
    allowed_document_types: list[PilotDocumentType] = Field(min_length=1, max_length=2)
    max_claims: int = Field(ge=1, le=20)
    max_documents: int = Field(ge=1, le=100)
    max_users: int = Field(ge=1, le=50)
    max_provider_runs: int = Field(ge=1, le=500)
    starts_at: datetime
    expires_at: datetime
    organization_authorization_reference: str = Field(min_length=8, max_length=500)
    data_owner_authorization_reference: str = Field(min_length=8, max_length=500)
    monitoring_reference: str = Field(min_length=8, max_length=500)
    incident_runbook_reference: str = Field(min_length=8, max_length=500)
    rollback_reference: str = Field(min_length=8, max_length=500)
    confirm_bounded_real_document_pilot: bool


class AIPrivatePilotApprovalWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_role: Literal["organization_owner", "data_owner"]
    action: Literal["approve", "reject"]
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)


class AIPrivatePilotDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["authorize_pilot", "hold"]
    confirm_decision: bool
    note: str = Field(min_length=10, max_length=4000)


class AIPrivatePilotDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: UUID
    document_id: UUID
    authorization_basis: Literal["organization_and_data_owner", "explicit_data_owner_consent"]
    authorization_reference: str = Field(min_length=8, max_length=500)
    data_minimization_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_real_non_restricted: bool


class AIPrivatePilotRunOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    human_review_action: Literal["approve", "edit", "reject"]
    output_candidate_count: int = Field(ge=0, le=10000)
    human_edit_count: int = Field(ge=0, le=10000)
    latency_ms: int = Field(ge=1, le=600000)
    observed_provider_cost_microusd: int = Field(ge=0, le=100000000)
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_human_review: bool


class AIPrivatePilotIncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal[
        "privacy", "security", "quality", "cost", "availability", "cross_tenant", "other"
    ]
    evidence_reference: str = Field(min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)
    confirm_pause: bool


class AIPrivatePilotIncidentResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution_reference: str = Field(min_length=8, max_length=500)
    resolution_note: str = Field(min_length=10, max_length=4000)
    resume_pilot: bool = False
    confirm_resolution: bool


class AIPrivatePilotRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_revoke: bool
    note: str = Field(min_length=10, max_length=4000)


class AIPrivatePilotComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_complete: bool
    note: str = Field(min_length=10, max_length=4000)


class AIPrivatePilotApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pilot_id: UUID
    approver_id: UUID | None
    approval_role: str
    action: str
    evidence_reference: str | None
    note: str
    approved_at: datetime
    created_at: datetime


class AIPrivatePilotDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pilot_id: UUID
    claim_id: UUID
    document_id: UUID
    attested_by_id: UUID | None
    revoked_by_id: UUID | None
    attestation_number: int
    document_type: str
    confidentiality_level: str
    authorization_basis: str
    authorization_reference: str
    data_minimization_reference: str
    note: str
    snapshot_hash: str
    status: str
    attested_at: datetime
    revoked_at: datetime | None
    revocation_note: str | None
    created_at: datetime


class AIPrivatePilotRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pilot_id: UUID
    eligibility_id: UUID
    claim_id: UUID
    document_id: UUID
    requested_by_id: UUID | None
    reviewed_by_id: UUID | None
    run_key: str
    processing_job_id: UUID
    task_type: str
    status: str
    human_review_action: str | None
    output_candidate_count: int | None
    human_edit_count: int | None
    latency_ms: int | None
    observed_provider_cost_microusd: int | None
    evidence_reference: str | None
    note: str | None
    outcome_hash: str | None
    queued_at: datetime
    reviewed_at: datetime | None
    created_at: datetime


class AIPrivatePilotIncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pilot_id: UUID
    reported_by_id: UUID | None
    resolved_by_id: UUID | None
    severity: str
    category: str
    evidence_reference: str
    note: str
    status: str
    reported_at: datetime
    resolved_at: datetime | None
    resolution_reference: str | None
    resolution_note: str | None
    created_at: datetime


class AIPrivatePilotResponse(BaseModel):
    id: UUID
    activation_request_id: UUID
    evaluation_suite_id: UUID
    requested_by_id: UUID | None
    finalized_by_id: UUID | None
    revoked_by_id: UUID | None
    attempt_number: int
    pilot_key: str
    data_mode: str
    allowed_document_types: list[str]
    max_claims: int
    max_documents: int
    max_users: int
    max_provider_runs: int
    starts_at: datetime
    expires_at: datetime
    organization_authorization_reference: str
    data_owner_authorization_reference: str
    monitoring_reference: str
    incident_runbook_reference: str
    rollback_reference: str
    status: str
    outcome: str | None
    decision_note: str | None
    decision_hash: str | None
    decided_at: datetime | None
    completed_at: datetime | None
    completion_note: str | None
    revoked_at: datetime | None
    revocation_note: str | None
    approvals: list[AIPrivatePilotApprovalResponse]
    document_eligibility: list[AIPrivatePilotDocumentResponse]
    runs: list[AIPrivatePilotRunResponse]
    incidents: list[AIPrivatePilotIncidentResponse]
    summary: dict
    created_at: datetime


class AIPrivatePilotDashboard(BaseModel):
    pilots: list[AIPrivatePilotResponse]

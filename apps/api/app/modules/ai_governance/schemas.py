from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["chief_engineer_report", "engine_log", "running_hours_record",
                       "pms_record", "workshop_report", "quotation", "invoice"]


class AIProviderActivationCreate(BaseModel):
    request_key: str = Field(min_length=8, max_length=120)
    environment: Literal["staging"] = "staging"
    provider: Literal["openai"] = "openai"
    provider_project_label: str = Field(min_length=3, max_length=180)
    model: str = Field(min_length=2, max_length=120)
    prompt_bundle_version: str = Field(min_length=3, max_length=80)
    schema_bundle_version: str = Field(min_length=3, max_length=80)
    data_mode: Literal["synthetic_deidentified"] = "synthetic_deidentified"
    allowed_document_types: list[DocumentType] = Field(min_length=1, max_length=7)
    restricted_documents_allowed: Literal[False] = False
    credential_storage_mode: Literal["environment", "secret_manager"]
    max_input_chars: int = Field(ge=1000, le=60000)
    max_output_tokens: int = Field(ge=128, le=4096)
    requests_per_minute: int = Field(ge=1, le=60)
    tokens_per_minute: int = Field(ge=1000, le=500000)
    monthly_spend_limit_cents: int = Field(ge=100, le=10000000)
    spend_alert_thresholds: list[int] = Field(min_length=1, max_length=5)
    retention_mode: Literal["approved_standard", "zero_retention_approved"]
    data_residency_region: str = Field(min_length=2, max_length=160)
    security_owner_label: str = Field(min_length=2, max_length=180)
    privacy_owner_label: str = Field(min_length=2, max_length=180)
    product_owner_label: str = Field(min_length=2, max_length=180)
    incident_owner_label: str = Field(min_length=2, max_length=180)
    kill_switch_owner_label: str = Field(min_length=2, max_length=180)
    credential_control_reference: str = Field(min_length=8, max_length=500)
    spend_limit_reference: str = Field(min_length=8, max_length=500)
    data_processing_reference: str = Field(min_length=8, max_length=500)
    kill_switch_reference: str = Field(min_length=8, max_length=500)
    evaluation_expires_at: datetime


class AIProviderActivationApprovalWrite(BaseModel):
    approval_role: Literal["security", "privacy", "product"]
    action: Literal["approve", "reject"]
    evidence_reference: str | None = Field(default=None, min_length=8, max_length=500)
    note: str = Field(min_length=10, max_length=4000)


class AIProviderActivationDecision(BaseModel):
    outcome: Literal["authorize_staging", "hold"]
    confirm_decision: bool
    note: str = Field(min_length=10, max_length=4000)


class AIProviderActivationRevoke(BaseModel):
    confirm_revoke: bool
    note: str = Field(min_length=10, max_length=4000)


class AIDocumentEligibilityCreate(BaseModel):
    activation_request_id: UUID
    claim_id: UUID
    document_id: UUID
    data_mode: Literal["synthetic", "deidentified"]
    evidence_reference: str = Field(min_length=8, max_length=500)
    confirm_eligible: bool
    note: str = Field(min_length=10, max_length=4000)


class AIDocumentEligibilityRevoke(BaseModel):
    confirm_revoke: bool
    note: str = Field(min_length=10, max_length=4000)


class AIProviderActivationApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    activation_request_id: UUID
    approver_id: UUID | None
    approval_role: str
    action: str
    evidence_reference: str | None
    note: str
    approved_at: datetime
    created_at: datetime


class AIProviderActivationResponse(BaseModel):
    id: UUID
    requested_by_id: UUID | None
    finalized_by_id: UUID | None
    revoked_by_id: UUID | None
    attempt_number: int
    request_key: str
    environment: str
    provider: str
    provider_project_label: str
    model: str
    prompt_bundle_version: str
    schema_bundle_version: str
    data_mode: str
    allowed_document_types: list[str]
    restricted_documents_allowed: bool
    credential_storage_mode: str
    max_input_chars: int
    max_output_tokens: int
    requests_per_minute: int
    tokens_per_minute: int
    monthly_spend_limit_cents: int
    spend_alert_thresholds: list[int]
    retention_mode: str
    data_residency_region: str
    security_owner_label: str
    privacy_owner_label: str
    product_owner_label: str
    incident_owner_label: str
    kill_switch_owner_label: str
    credential_control_reference: str
    spend_limit_reference: str
    data_processing_reference: str
    kill_switch_reference: str
    evaluation_expires_at: datetime
    status: str
    outcome: str | None
    decision_note: str | None
    decision_hash: str | None
    decided_at: datetime | None
    revoked_at: datetime | None
    revocation_note: str | None
    approvals: list[AIProviderActivationApprovalResponse]
    summary: dict
    created_at: datetime


class AIDocumentEligibilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    activation_request_id: UUID
    claim_id: UUID
    document_id: UUID
    attested_by_id: UUID | None
    revoked_by_id: UUID | None
    attestation_number: int
    data_mode: str
    document_type: str
    confidentiality_level: str
    evidence_reference: str
    note: str
    snapshot_hash: str
    status: str
    attested_at: datetime
    revoked_at: datetime | None
    revocation_note: str | None
    created_at: datetime


class AIGovernanceDashboard(BaseModel):
    activation_requests: list[AIProviderActivationResponse]
    document_eligibility: list[AIDocumentEligibilityResponse]

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DisposalReleaseReviewRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class DisposalReleaseReviewDecision(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class DisposalReleaseReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    disposal_quarantine_stage_id: UUID
    disposal_dry_run_ceremony_id: UUID
    disposal_execution_manifest_id: UUID
    disposal_authorization_id: UUID
    retention_policy_id: UUID
    manifest_hash: str
    inventory_hash: str
    authorization_lineage_hash: str
    ceremony_hash: str
    plan_hash: str
    attestation_hash: str
    overlay_hash: str
    stage_hash: str
    retention_policy_number: int
    retention_policy_hash: str
    release_snapshot: dict[str, Any]
    release_snapshot_hash: str
    review_hash: str
    document_count: int
    total_file_size_bytes: int
    quarantine_staged_by_id: UUID
    quarantine_staged_at: datetime
    quarantine_stage_expires_at: datetime
    minimum_release_eligible_at: datetime
    requested_by_id: UUID
    request_reason: str
    requested_at: datetime
    review_expires_at: datetime
    last_revalidated_at: datetime | None
    status: str
    approved_by_id: UUID | None
    approved_at: datetime | None
    approval_reason: str | None
    approval_hash: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    created_at: datetime
    updated_at: datetime

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DisposalQuarantineStageOpen(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class DisposalQuarantineStageDecision(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class DisposalQuarantineStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
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
    retention_policy_number: int
    retention_policy_hash: str
    ceremony_expires_at: datetime
    overlay_plan: list[dict[str, Any]]
    overlay_hash: str
    stage_hash: str
    document_count: int
    total_file_size_bytes: int
    staged_by_id: UUID
    staging_reason: str
    staged_at: datetime
    stage_expires_at: datetime
    last_revalidated_at: datetime | None
    status: str
    restored_by_id: UUID | None
    restored_at: datetime | None
    restoration_reason: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    created_at: datetime
    updated_at: datetime

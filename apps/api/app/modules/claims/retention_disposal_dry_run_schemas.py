from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DisposalDryRunCeremonyOpen(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class DisposalDryRunCeremonyDecision(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class DisposalDryRunCeremonyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    disposal_execution_manifest_id: UUID
    disposal_authorization_id: UUID
    retention_policy_id: UUID
    manifest_hash: str
    inventory_hash: str
    authorization_lineage_hash: str
    retention_policy_number: int
    retention_policy_hash: str
    manifest_expires_at: datetime
    dry_run_plan: list[dict[str, Any]]
    plan_hash: str
    ceremony_hash: str
    document_count: int
    total_file_size_bytes: int
    created_by_id: UUID
    opening_reason: str
    opened_at: datetime
    ceremony_expires_at: datetime
    last_revalidated_at: datetime | None
    status: str
    attested_by_id: UUID | None
    attested_at: datetime | None
    attestation_hash: str | None
    attestation_reason: str | None
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    created_at: datetime
    updated_at: datetime

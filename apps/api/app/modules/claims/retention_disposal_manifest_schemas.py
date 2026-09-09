from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DisposalExecutionManifestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    claim_id: UUID
    disposal_authorization_id: UUID
    retention_policy_id: UUID
    retention_policy_number: int
    retention_policy_hash: str
    authorization_lineage_hash: str
    authorization_snapshot_hash: str
    authorization_state_fingerprint: str
    authorization_expires_at: datetime
    inventory: list[dict[str, Any]]
    inventory_hash: str
    manifest_hash: str
    document_count: int
    total_file_size_bytes: int
    active_hold_ids: list[str]
    pending_proposal_ids: list[str]
    created_by_id: UUID
    evaluated_at: datetime
    manifest_expires_at: datetime
    last_revalidated_at: datetime | None
    status: str
    terminal_by_id: UUID | None
    terminal_at: datetime | None
    terminal_reason: str | None
    created_at: datetime
    updated_at: datetime

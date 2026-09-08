from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MfaFactorResetCreate(BaseModel):
    user_id: UUID
    factor_id: UUID
    reason: str = Field(min_length=10, max_length=500)


class MfaFactorResetReject(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class MfaFactorResetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    factor_id: UUID
    requested_by_id: UUID
    requested_auth_session_id: UUID
    reason: str
    status: str
    approved_at: datetime | None = None
    approved_by_id: UUID | None = None
    approved_auth_session_id: UUID | None = None
    rejected_at: datetime | None = None
    rejected_by_id: UUID | None = None
    rejected_auth_session_id: UUID | None = None
    rejection_reason: str | None = None
    cancelled_at: datetime | None = None
    cancelled_by_id: UUID | None = None
    cancelled_auth_session_id: UUID | None = None
    executed_at: datetime | None = None
    executed_by_id: UUID | None = None
    executed_auth_session_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class MfaFactorResetExecutionResult(BaseModel):
    request: MfaFactorResetRead
    invalidated_recovery_codes: int
    revoked_sessions: int

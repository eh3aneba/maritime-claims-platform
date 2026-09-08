from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WebAuthnCredentialResetCreate(BaseModel):
    user_id: UUID
    credential_id: UUID
    reason: str = Field(min_length=10, max_length=500)


class WebAuthnCredentialResetReject(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class WebAuthnCredentialResetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    credential_id: UUID
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
    reenrollment_expires_at: datetime | None = None
    reenrollment_claimed_at: datetime | None = None
    reenrollment_auth_session_id: UUID | None = None
    reenrollment_consumed_at: datetime | None = None
    reenrollment_credential_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class WebAuthnCredentialResetExecutionResult(BaseModel):
    request: WebAuthnCredentialResetRead
    cancelled_registration_transactions: int
    cancelled_authentication_transactions: int
    revoked_sessions: int
    reenrollment_authorized: bool

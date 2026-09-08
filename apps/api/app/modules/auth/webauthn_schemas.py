from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WebAuthnRelyingPartyProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rp_id: str = Field(min_length=1, max_length=253)
    rp_name: str = Field(min_length=1, max_length=200)
    allowed_origins: list[str] = Field(min_length=1, max_length=10)
    user_verification: Literal["required"] = "required"
    attestation: Literal["none"] = "none"


class WebAuthnRelyingPartyProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    profile_number: int
    rp_id: str
    rp_name: str
    allowed_origins: list[str]
    user_verification: str
    attestation: str
    profile_hash: str
    previous_profile_hash: str | None
    created_by_id: UUID
    created_at: datetime


class WebAuthnRegistrationRp(BaseModel):
    id: str
    name: str


class WebAuthnRegistrationUser(BaseModel):
    id: str
    name: str
    display_name: str


class WebAuthnCredentialParameter(BaseModel):
    type: Literal["public-key"] = "public-key"
    alg: int


class WebAuthnAuthenticatorSelection(BaseModel):
    user_verification: Literal["required"] = "required"
    resident_key: Literal["preferred"] = "preferred"


class WebAuthnRegistrationBeginResponse(BaseModel):
    transaction_id: UUID
    challenge: str
    expires_at: datetime
    timeout_ms: int
    rp: WebAuthnRegistrationRp
    user: WebAuthnRegistrationUser
    pub_key_cred_params: list[WebAuthnCredentialParameter]
    authenticator_selection: WebAuthnAuthenticatorSelection
    attestation: Literal["none"] = "none"


class WebAuthnRegistrationTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    auth_session_id: UUID
    profile_id: UUID
    profile_number: int
    profile_hash: str
    expires_at: datetime
    consumed_at: datetime | None
    cancelled_at: datetime | None

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
    resident_key: Literal["required"] = "required"


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


class WebAuthnRegistrationFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_id: str = Field(min_length=16, max_length=1400)
    client_data_json: str = Field(min_length=16, max_length=24000)
    attestation_object: str = Field(min_length=16, max_length=90000)


class WebAuthnRegistrationTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    auth_session_id: UUID
    profile_id: UUID
    profile_number: int
    profile_hash: str
    reenrollment_reset_request_id: UUID | None = None
    expires_at: datetime
    consumed_at: datetime | None
    cancelled_at: datetime | None


class WebAuthnCredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    profile_id: UUID
    profile_number: int
    profile_hash: str
    registration_transaction_id: UUID
    algorithm: int
    sign_count: int
    aaguid: str
    attestation_format: str
    created_at: datetime
    revoked_at: datetime | None


class WebAuthnAuthenticationBeginResponse(BaseModel):
    transaction_id: UUID
    challenge: str
    expires_at: datetime
    timeout_ms: int
    rp_id: str
    user_verification: Literal["required"] = "required"


class WebAuthnAuthenticationFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_id: str = Field(min_length=16, max_length=1400)
    client_data_json: str = Field(min_length=16, max_length=24000)
    authenticator_data: str = Field(min_length=16, max_length=6000)
    signature: str = Field(min_length=16, max_length=3000)


class WebAuthnAuthenticationTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    auth_session_id: UUID
    profile_id: UUID
    profile_number: int
    profile_hash: str
    credential_id: UUID | None
    expires_at: datetime
    consumed_at: datetime | None
    cancelled_at: datetime | None


class WebAuthnAuthenticationVerifiedResponse(BaseModel):
    auth_session_id: UUID
    mfa_verified_at: datetime
    mfa_method: Literal["webauthn"] = "webauthn"
    authentication_transaction_id: UUID
    credential_id: UUID
    sign_count: int

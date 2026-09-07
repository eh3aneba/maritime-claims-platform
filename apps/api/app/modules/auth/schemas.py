from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.users.schemas import UserRead


class LoginRequest(BaseModel):
    organization_slug: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class AuthSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    identity_source: str
    auth_method: str
    created_at: datetime
    expires_at: datetime


class EnterpriseIdentityProviderCreate(BaseModel):
    provider_key: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$",
    )
    display_name: str = Field(min_length=2, max_length=160)
    protocol: Literal["oidc", "saml"]
    issuer_identifier: str = Field(min_length=3, max_length=500)


class EnterpriseIdentityProviderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    provider_key: str
    display_name: str
    protocol: str
    issuer_identifier: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class ExternalIdentityBindingCreate(BaseModel):
    user_id: UUID
    external_subject: str = Field(min_length=1, max_length=1024)


class ExternalIdentityBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    provider_id: UUID
    user_id: UUID
    subject_fingerprint: str
    created_at: datetime
    revoked_at: datetime | None
    revoked_by_id: UUID | None
    revocation_reason: str | None


class OidcTrustProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: str = Field(min_length=1, max_length=500)
    jwks_uri: str = Field(min_length=8, max_length=1000)
    allowed_algorithms: list[Literal["RS256", "ES256"]] = Field(
        min_length=1,
        max_length=2,
    )

    @field_validator("allowed_algorithms")
    @classmethod
    def algorithms_must_be_unique(
        cls,
        value: list[Literal["RS256", "ES256"]],
    ) -> list[Literal["RS256", "ES256"]]:
        if len(value) != len(set(value)):
            raise ValueError("OIDC signing algorithms must be unique")
        return value


class OidcTrustProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    provider_id: UUID
    profile_number: int
    issuer_identifier: str
    audience: str
    jwks_uri: str
    allowed_algorithms: list[str]
    profile_hash: str
    previous_profile_hash: str | None
    created_by_id: UUID
    created_at: datetime


class OidcRuntimeProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_endpoint: str = Field(min_length=8, max_length=1000)
    token_endpoint: str = Field(min_length=8, max_length=1000)
    redirect_uri: str = Field(min_length=8, max_length=1000)
    scopes: list[Literal["openid", "profile", "email"]] = Field(
        min_length=1,
        max_length=3,
    )
    client_auth_method: Literal["none", "client_secret_basic"]

    @field_validator("scopes")
    @classmethod
    def scopes_must_be_unique_and_include_openid(
        cls,
        value: list[Literal["openid", "profile", "email"]],
    ) -> list[Literal["openid", "profile", "email"]]:
        if len(value) != len(set(value)):
            raise ValueError("OIDC runtime scopes must be unique")
        if "openid" not in value:
            raise ValueError("OIDC runtime scopes must include openid")
        return value


class OidcRuntimeProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    provider_id: UUID
    trust_profile_id: UUID
    trust_profile_number: int
    trust_profile_hash: str
    runtime_profile_number: int
    authorization_endpoint: str
    token_endpoint: str
    redirect_uri: str
    scopes: list[str]
    client_auth_method: str
    runtime_profile_hash: str
    previous_runtime_profile_hash: str | None
    created_by_id: UUID
    created_at: datetime


class OidcAuthorizationTransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_slug: str = Field(
        min_length=2,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]$",
    )
    provider_key: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$",
    )


class OidcAuthorizationTransactionStartResponse(BaseModel):
    transaction_id: UUID
    provider_key: str
    provider_display_name: str
    issuer_identifier: str
    audience: str
    trust_profile_id: UUID
    trust_profile_number: int
    trust_profile_hash: str
    runtime_profile_id: UUID
    runtime_profile_number: int
    runtime_profile_hash: str
    authorization_endpoint: str
    token_endpoint: str
    redirect_uri: str
    scopes: list[str]
    client_auth_method: str
    state: str
    nonce: str
    code_verifier: str
    code_challenge: str
    code_challenge_method: Literal["S256"] = "S256"
    expires_at: datetime

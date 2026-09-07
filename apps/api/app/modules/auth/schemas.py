from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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

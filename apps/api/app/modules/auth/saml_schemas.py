from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SamlTrustRuntimeProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idp_sso_url: str = Field(min_length=8, max_length=1000)
    sp_entity_id: str = Field(min_length=1, max_length=500)
    acs_url: str = Field(min_length=8, max_length=1000)
    authn_request_binding: Literal["HTTP-Redirect"] = "HTTP-Redirect"
    response_binding: Literal["HTTP-POST"] = "HTTP-POST"
    allowed_signature_algorithms: list[str] = Field(
        default_factory=lambda: ["RSA-SHA256"], min_length=1, max_length=4
    )
    allowed_digest_algorithms: list[str] = Field(
        default_factory=lambda: ["SHA-256"], min_length=1, max_length=4
    )
    idp_signing_certificate_pem: str = Field(min_length=100, max_length=20000)


class SamlTrustRuntimeProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    provider_id: UUID
    profile_number: int
    idp_entity_identifier: str
    idp_sso_url: str
    sp_entity_id: str
    acs_url: str
    authn_request_binding: str
    response_binding: str
    allowed_signature_algorithms: list[str]
    allowed_digest_algorithms: list[str]
    idp_signing_certificate_pem: str
    certificate_sha256: str
    profile_hash: str
    previous_profile_hash: str | None
    created_by_id: UUID
    created_at: datetime

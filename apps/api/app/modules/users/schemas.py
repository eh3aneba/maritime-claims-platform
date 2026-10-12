from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.users.models import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=12, max_length=256)
    role: UserRole = UserRole.CLAIMS_HANDLER


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool


class UserDeactivateRequest(BaseModel):
    """Explicit, privacy-safe human change ticket; never a free-text secret."""

    change_ticket_ref: str = Field(
        min_length=6, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    )
    confirmation: Literal["DEACTIVATE_USER"]


class UserDeactivateRead(BaseModel):
    id: UUID
    is_active: Literal[False] = False
    newly_deactivated: bool
    sessions_revoked: int = Field(ge=0)
    # External IdP/provider credentials and background integrations are NOT
    # deprovisioned by this app-local action; operators must handle separately.
    external_identity_deprovisioned: Literal[False] = False
    external_integrations_disabled: Literal[False] = False

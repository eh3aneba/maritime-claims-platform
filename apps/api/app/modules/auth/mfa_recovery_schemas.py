from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MfaRecoveryCodeVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=32, max_length=64)


class MfaRecoveryCodeBatchResponse(BaseModel):
    factor_id: UUID
    batch_id: UUID
    recovery_codes: list[str] = Field(min_length=10, max_length=10)
    count: Literal[10] = 10

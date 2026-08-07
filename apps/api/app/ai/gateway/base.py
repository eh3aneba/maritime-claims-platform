from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class AIProviderUnavailable(RuntimeError):
    pass


class AIRequest(BaseModel):
    task: str
    system_instructions: str
    input_text: str
    schema_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIResponse(BaseModel):
    provider: str
    model: str
    output_text: str | None = None
    structured_output: dict[str, Any] | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    raw_response_id: str | None = None


class AIProvider(Protocol):
    name: str

    def generate(self, request: AIRequest) -> AIResponse:
        ...

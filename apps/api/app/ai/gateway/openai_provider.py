from __future__ import annotations

import json
from typing import Any

from app.ai.gateway.base import AIProviderUnavailable, AIRequest, AIResponse


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, api_key: str, model: str, max_output_tokens: int = 2000) -> None:
        if not api_key:
            raise AIProviderUnavailable("OPENAI_API_KEY is not configured.")
        if not model:
            raise AIProviderUnavailable("AI_MODEL is not configured.")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise AIProviderUnavailable("The openai Python package is not installed.") from exc
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._max_output_tokens = max_output_tokens

    def generate(self, request: AIRequest) -> AIResponse:
        if request.output_schema is None or request.schema_name is None:
            raise ValueError("Structured output requests require schema_name and output_schema.")

        response = self._client.responses.create(
            model=self._model,
            instructions=request.system_instructions,
            input=request.input_text,
            max_output_tokens=getattr(self, "_max_output_tokens", 2000),
            text={
                "format": {
                    "type": "json_schema",
                    "name": request.schema_name,
                    "schema": request.output_schema,
                    "strict": True,
                }
            },
        )
        output_text = response.output_text
        if not output_text:
            raise RuntimeError("AI provider returned no structured output text.")
        try:
            structured = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("AI provider returned invalid JSON despite structured output mode.") from exc

        usage: dict[str, int] = {}
        raw_usage: Any = getattr(response, "usage", None)
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(raw_usage, name, None) if raw_usage is not None else None
            if isinstance(value, int):
                usage[name] = value

        return AIResponse(
            provider=self.name,
            model=self._model,
            output_text=output_text,
            structured_output=structured,
            usage=usage,
            raw_response_id=getattr(response, "id", None),
        )

"""Synthetic-only localhost Ollama experiment behind the existing AIProvider contract.

Not a production/pilot provider. The *only* network destination is fixed
IPv4 loopback, with no proxies, redirects, DNS, external models or credentials.
Existing Claim/Document AI requests are not eligible: require exact synthetic
metadata and the explicitly pinned small local prototype model.
"""
from __future__ import annotations

import http.client
import json
from typing import Any

from app.ai.gateway.base import AIProviderUnavailable, AIRequest, AIResponse

_LOCAL_MODEL = "qwen3:1.7b"
_MAX_INPUT_CHARS = 4096
_MAX_REQUEST_BYTES = 65536
_MAX_RESPONSE_BYTES = 65536
_MAX_PREDICT = 512


class OllamaLocalExperimentalProvider:
    name = "ollama_local"

    def __init__(self, *, model: str, max_output_tokens: int = _MAX_PREDICT) -> None:
        if model != _LOCAL_MODEL:
            raise AIProviderUnavailable("local_ai_model_not_allowlisted")
        if (
            type(max_output_tokens) is not int
            or not 1 <= max_output_tokens <= _MAX_PREDICT
        ):
            raise AIProviderUnavailable("local_ai_unsafe_output_budget")
        self._model = model
        self._max_output_tokens = max_output_tokens

    def generate(self, request: AIRequest) -> AIResponse:
        # Explicit synthetic-only marker: normal claim jobs carry document_id,
        # claim_id, etc., so they can never silently use this experimental path.
        if request.metadata != {"synthetic_local_ai_test": True}:
            raise AIProviderUnavailable("local_ai_synthetic_only")
        if (
            not request.schema_name
            or not isinstance(request.output_schema, dict)
            or not request.output_schema
            or not request.system_instructions.strip()
            or len(request.system_instructions) > _MAX_INPUT_CHARS
            or not request.input_text.strip()
            or len(request.input_text) > _MAX_INPUT_CHARS
        ):
            raise AIProviderUnavailable("local_ai_invalid_request")

        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": request.system_instructions + "\n\n" + request.input_text,
            "format": request.output_schema,
            "stream": False,
            "think": False,
            "keep_alive": 0,
            "options": {
                "num_ctx": 4096,
                "num_predict": self._max_output_tokens,
                "temperature": 0,
            },
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > _MAX_REQUEST_BYTES:
            raise AIProviderUnavailable("local_ai_request_too_large")

        # stdlib HTTPConnection with a *literal* IP/port: no DNS resolver,
        # ProxyHandler, redirects, URL interpolation or outbound AI API.
        conn = http.client.HTTPConnection("127.0.0.1", 11434, timeout=10)
        try:
            conn.request(
                "POST", "/api/generate", body=body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response = conn.getresponse()
            if response.status != 200:
                raise AIProviderUnavailable("local_ai_unavailable")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise AIProviderUnavailable("local_ai_response_too_large")
        except AIProviderUnavailable:
            raise
        except (OSError, TimeoutError, http.client.HTTPException):
            raise AIProviderUnavailable("local_ai_unavailable") from None
        finally:
            conn.close()

        try:
            result = json.loads(raw)
            if (
                type(result) is not dict
                or result.get("done") is not True
                or result.get("model") != self._model
                or not isinstance(result.get("response"), str)
            ):
                raise AIProviderUnavailable("local_ai_invalid_response")
            structured = json.loads(result["response"])
            if type(structured) is not dict:
                raise AIProviderUnavailable("local_ai_invalid_response")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise AIProviderUnavailable("local_ai_invalid_response") from None

        usage: dict[str, int] = {}
        for native, common in (
            ("prompt_eval_count", "input_tokens"),
            ("eval_count", "output_tokens"),
        ):
            value = result.get(native)
            if type(value) is int and 0 <= value <= 100000:
                usage[common] = value
        return AIResponse(
            provider=self.name, model=self._model, output_text=result["response"],
            structured_output=structured, usage=usage,
        )

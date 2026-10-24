"""Synthetic-only, no-network contract tests for the localhost Ollama adapter."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.ai.gateway.base import AIProviderUnavailable, AIRequest
from app.ai.gateway.disabled import DisabledAIProvider
from app.ai.gateway.ollama_local import OllamaLocalExperimentalProvider
from app.ai.gateway.registry import get_ai_provider


def _request(*, metadata=None, **overrides):
    data = {
        "task": "synthetic_hm_extraction",
        "system_instructions": "Quote only directly stated facts. No liability decisions.",
        "input_text": "Synthetic Chief Engineer report: abnormal vibration.",
        "schema_name": "synthetic_hm_v1",
        "output_schema": {"type": "object", "properties": {"quote": {"type": "string"}},
                          "required": ["quote"], "additionalProperties": False},
        "metadata": {"synthetic_local_ai_test": True} if metadata is None else metadata,
    }
    data.update(overrides)
    return AIRequest(**data)


class _FakeResponse:
    status = 200
    raw = None

    def __init__(self, *, status=200, payload=None, raw=None):
        self.status = status
        self.raw = (
            raw if raw is not None
            else json.dumps(payload if payload is not None else {
                "model": "qwen3:1.7b", "done": True,
                "response": '{"quote":"abnormal vibration"}',
                "prompt_eval_count": 33, "eval_count": 6,
            }).encode("utf-8")
        )

    def read(self, _size):
        return self.raw


class _FakeConnection:
    def __init__(self, response=None, problem=None):
        self.response = response or _FakeResponse()
        self.problem = problem
        self.request_args = None
        self.closed = False

    def request(self, method, path, *, body, headers):
        if self.problem:
            raise self.problem
        self.request_args = (method, path, json.loads(body), headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def _provider():
    return OllamaLocalExperimentalProvider(model="qwen3:1.7b", max_output_tokens=256)


def _settings(*, provider="disabled", env="development", enabled=False):
    return SimpleNamespace(
        ai_provider=provider, ai_model="qwen3:1.7b",
        app_env=env, ai_local_experimental_enabled=enabled,
        ai_max_output_tokens=256,
    )


@pytest.mark.parametrize("env", ["pilot", "staging", "production"])
def test_production_facing_registry_never_exposes_local_experiment(env):
    with patch("app.ai.gateway.registry.get_settings", return_value=_settings(
        provider="ollama_local", env=env, enabled=True,
    )):
        with pytest.raises(AIProviderUnavailable, match="local_ai_development_only"):
            get_ai_provider()


def test_default_provider_is_still_disabled_and_local_optin_is_required():
    with patch("app.ai.gateway.registry.get_settings", return_value=_settings()):
        assert isinstance(get_ai_provider(), DisabledAIProvider)
    with patch("app.ai.gateway.registry.get_settings", return_value=_settings(
        provider="ollama_local", enabled=False,
    )):
        with pytest.raises(AIProviderUnavailable, match="local_ai_development_only"):
            get_ai_provider()
    with patch("app.ai.gateway.registry.get_settings", return_value=_settings(
        provider="ollama_local", enabled=True,
    )):
        assert isinstance(get_ai_provider(), OllamaLocalExperimentalProvider)


def test_only_fixed_loopback_and_structured_no_think_request():
    conn = _FakeConnection()
    calls = []

    def constructor(host, port, timeout):
        calls.append((host, port, timeout))
        return conn

    with patch("app.ai.gateway.ollama_local.http.client.HTTPConnection", side_effect=constructor):
        result = _provider().generate(_request())
    assert calls == [("127.0.0.1", 11434, 30)]
    method, path, body, headers = conn.request_args
    assert (method, path) == ("POST", "/api/generate")
    assert body["model"] == "qwen3:1.7b"
    assert body["keep_alive"] == "1m"
    assert body["think"] is False and body["stream"] is False
    assert body["format"]["additionalProperties"] is False
    assert body["options"]["num_predict"] == 256
    assert headers == {"Content-Type": "application/json", "Accept": "application/json"}
    assert "OPENAI_API_KEY" not in json.dumps(body)
    assert conn.closed is True
    assert result.structured_output == {"quote": "abnormal vibration"}
    assert result.usage == {"input_tokens": 33, "output_tokens": 6}
    assert result.provider == "ollama_local"


def test_two_sequential_synthetic_requests_retain_fixed_local_model_only():
    connections = []

    def constructor(host, port, timeout):
        assert (host, port, timeout) == ("127.0.0.1", 11434, 30)
        conn = _FakeConnection()
        connections.append(conn)
        return conn

    provider = _provider()
    with patch("app.ai.gateway.ollama_local.http.client.HTTPConnection",
               side_effect=constructor):
        provider.generate(_request())
        provider.generate(_request())
    assert len(connections) == 2
    for conn in connections:
        assert conn.closed is True
        method, path, body, headers = conn.request_args
        assert (method, path) == ("POST", "/api/generate")
        assert body["keep_alive"] == "1m"
        assert body["model"] == "qwen3:1.7b"
        assert body["think"] is False
        assert body["stream"] is False
        assert body["options"]["num_ctx"] == 4096


@pytest.mark.parametrize("metadata", [
    {}, {"claim_id": "synthetic-but-doc-context"},
    {"synthetic_local_ai_test": True, "document_id": "real"},
    {"synthetic_local_ai_test": 1},
])
def test_real_claim_job_or_loose_synthetic_label_never_reaches_network(metadata):
    with patch("app.ai.gateway.ollama_local.http.client.HTTPConnection") as network:
        with pytest.raises(AIProviderUnavailable, match="local_ai_synthetic_only"):
            _provider().generate(_request(metadata=metadata))
        network.assert_not_called()


def test_invalid_schema_and_budget_are_denied_before_network():
    for kwargs in (
        {"schema_name": None},
        {"output_schema": None},
        {"input_text": "X" * 4097},
        {"system_instructions": "X" * 4097},
    ):
        with patch("app.ai.gateway.ollama_local.http.client.HTTPConnection") as network:
            with pytest.raises(AIProviderUnavailable, match="local_ai_invalid_request"):
                _provider().generate(_request(**kwargs))
            network.assert_not_called()
    with pytest.raises(AIProviderUnavailable, match="local_ai_model_not_allowlisted"):
        OllamaLocalExperimentalProvider(model="qwen3:latest")
    with pytest.raises(AIProviderUnavailable, match="local_ai_unsafe_output_budget"):
        OllamaLocalExperimentalProvider(model="qwen3:1.7b", max_output_tokens=10000)


@pytest.mark.parametrize("response,expected_code", [
    (_FakeResponse(status=503), "local_ai_unavailable"),
    (_FakeResponse(raw=b"not JSON"), "local_ai_invalid_response"),
    (_FakeResponse(payload={"model": "qwen3:1.7b", "done": False, "response": "{}"}),
     "local_ai_invalid_response"),
    (_FakeResponse(payload={"model": "not-the-pinned-model", "done": True, "response": "{}"}),
     "local_ai_invalid_response"),
    (_FakeResponse(payload={"model": "qwen3:1.7b", "done": True, "response": "[]"}),
     "local_ai_invalid_response"),
    (_FakeResponse(raw=b"x" * 65537), "local_ai_response_too_large"),
])
def test_bad_model_response_fails_closed_without_leaking_body(response, expected_code):
    conn = _FakeConnection(response=response)
    with patch("app.ai.gateway.ollama_local.http.client.HTTPConnection", return_value=conn):
        with pytest.raises(AIProviderUnavailable) as ex:
            _provider().generate(_request())
    assert str(ex.value) == expected_code
    assert conn.closed


def test_transport_failure_hides_private_provider_errors():
    conn = _FakeConnection(problem=ConnectionRefusedError("private user/path secret"))
    with patch("app.ai.gateway.ollama_local.http.client.HTTPConnection", return_value=conn):
        with pytest.raises(AIProviderUnavailable) as ex:
            _provider().generate(_request())
    assert str(ex.value) == "local_ai_unavailable"
    assert "private" not in str(ex.value)
    assert conn.closed



def test_timeout_after_request_fails_closed_and_closes_socket():
    class _TimedOutResponse(_FakeResponse):
        def read(self, _size):
            raise TimeoutError("sensitive localhost timing or fixture details")

    conn = _FakeConnection(response=_TimedOutResponse())
    with patch("app.ai.gateway.ollama_local.http.client.HTTPConnection", return_value=conn):
        with pytest.raises(AIProviderUnavailable) as ex:
            _provider().generate(_request())
    assert str(ex.value) == "local_ai_unavailable"
    assert "sensitive" not in str(ex.value)
    assert conn.closed


def test_preflight_refuses_local_experiment_in_strict_environments(tmp_path):
    from app.core import preflight

    for env in ("pilot", "staging", "production"):
        settings = SimpleNamespace(
            app_env=env, cors_origins=["https://example.test"],
            secret_key="a" * 48, database_url="postgresql://user:pass@example.test/db",
            next_public_api_base_url="https://example.test",
            ai_provider="ollama_local", ai_model="qwen3:1.7b",
            ai_local_experimental_enabled=True,
            storage_backend="local", local_storage_path=str(tmp_path),
            malware_scan_enabled=False,
            s3_foundation_enabled=False,
        )
        with patch("app.core.preflight.get_settings", return_value=settings):
            errors, _warnings = preflight.run_preflight(require_db=False)
        assert "Experimental local AI is forbidden in pilot/staging/production" in errors

"""Prevent experimental Ollama from becoming a production/provider bypass."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "apps/api/app/ai/gateway/ollama_local.py"
REGISTRY = ROOT / "apps/api/app/ai/gateway/registry.py"
CONFIG = ROOT / "apps/api/app/core/config.py"
PREFLIGHT = ROOT / "apps/api/app/core/preflight.py"
TESTS = ROOT / "apps/api/tests/test_ollama_local_experimental.py"
DOC = ROOT / "docs/operations/OLLAMA_LOCAL_DEV_ADAPTER.md"


class LocalOllamaDevelopmentBoundaryPolicy(unittest.TestCase):
    def test_adapter_only_calls_literal_loopback_and_never_logs_source(self):
        s = ADAPTER.read_text(encoding="utf-8")
        for fragment in (
            'name = "ollama_local"',
            '_LOCAL_MODEL = "qwen3:1.7b"',
            'request.metadata != {"synthetic_local_ai_test": True}',
            'type(request.metadata.get("synthetic_local_ai_test")) is not bool',
            'http.client.HTTPConnection("127.0.0.1", 11434, timeout=10)',
            '"POST", "/api/generate"',
            '"think": False', '"stream": False',
            'response.read(_MAX_RESPONSE_BYTES + 1)',
            'result.get("model") != self._model',
            'raise AIProviderUnavailable("local_ai_unavailable")',
        ):
            self.assertIn(fragment, s)
        for forbidden in (
            'urlopen(', 'requests.post(', 'httpx.post(', 'OpenAI(',
            'getaddrinfo(', 'ProxyHandler(', 'print(', 'logging.',
            'document_id=', 'claim_id=', 'OPENAI_API_KEY',
        ):
            self.assertNotIn(forbidden, s)

    def test_activation_is_false_by_default_and_denied_in_strict_environments(self):
        registry = REGISTRY.read_text(encoding="utf-8")
        config = CONFIG.read_text(encoding="utf-8")
        preflight = PREFLIGHT.read_text(encoding="utf-8")
        self.assertIn('ai_provider: str = "disabled"', config)
        self.assertIn('ai_local_experimental_enabled: bool = False', config)
        self.assertIn('if settings.ai_provider == "ollama_local":', registry)
        self.assertIn('settings.app_env.lower().strip() not in {"development", "test"}', registry)
        self.assertIn('not settings.ai_local_experimental_enabled', registry)
        self.assertIn('if settings.ai_provider.lower() == "ollama_local":', preflight)
        self.assertIn('if env not in {"development", "test"}:', preflight)
        self.assertIn('Experimental local AI is forbidden in pilot/staging/production', preflight)

    def test_focused_runtime_mock_tests_and_operator_limitations(self):
        source = TESTS.read_text(encoding="utf-8")
        doc = DOC.read_text(encoding="utf-8")
        for fragment in (
            'test_only_fixed_loopback_and_structured_no_think_request',
            'test_real_claim_job_or_loose_synthetic_label_never_reaches_network',
            'test_transport_failure_hides_private_provider_errors',
            'test_preflight_refuses_local_experiment_in_strict_environments',
            'test_bad_model_response_fails_closed_without_leaking_body',
            'network.assert_not_called()',
        ):
            self.assertIn(fragment, source)
        self.assertIn('not deployed, not tested against a real Ollama daemon', doc)
        self.assertIn('No real customer files', doc)
        self.assertIn('Pilot GO remains NO', doc)


if __name__ == "__main__":
    unittest.main()

"""Always-on production-policy AST and negative-test guard for local probe."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
CODE = ROOT / "scripts/pilot_local_ai_ollama_timing_probe.py"
TEST = ROOT / "scripts/tests/test_pilot_local_ai_ollama_timing_probe.py"
GUIDE = ROOT / "docs/operations/LOCAL_AI_OLLAMA_TIMING_PROBE.md"


class LocalTimingProbePolicy(unittest.TestCase):
    def test_literal_model_loopback_and_only_manual_no_production_path(self):
        source = CODE.read_text(encoding="utf-8")
        names = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module)
        self.assertEqual(names, {"__future__", "http.client", "json", "sys", "time", "typing"})
        for expected in (
            '_MODEL = "qwen3:1.7b"', '_HOST = "127.0.0.1"',
            "_PORT = 11434", "_TIMEOUT_SECONDS = 90", "_TRIALS = 2",
            '"keep_alive": "1m"', '"num_predict": 16',
            '"POST", "/api/generate"',
            "response.read(_MAX_RESPONSE_BYTES + 1)",
            'args != _FLAGS',
            '"first_trial_known_cold": False',
            '"second_trial_proven_warm": False',
            '"network_egress_isolation_verified": False',
            '"pilot_accepted": False',
            'print("local_ollama_timing_probe_failed")',
        ):
            self.assertIn(expected, source)
        for prohibited in (
            "open(", "read_text(", "write_text(", "write_bytes(",
            "input(", "os.environ", "subprocess", "requests.", "OpenAI(",
            "get_ai_provider(", "claim_id", "document_id", "DATABASE_URL",
            '"host":', "localhost:80", 'headers={"Authorization"',
        ):
            self.assertNotIn(prohibited, source)

    def test_negative_cases_and_runbook(self):
        tests = TEST.read_text(encoding="utf-8")
        for expected in (
            "test_exact_two_fixed_loopback_calls_never_return_text",
            "test_network_timeout_is_sanitized_and_second_trial_still_attempted",
            "test_untrusted_timing_model_shape_and_oversized_response_fail_closed",
            "test_cli_requires_exact_manual_flag_without_model_call",
            "test_cli_never_leaks_dynamic_exception_text",
        ):
            self.assertIn(expected, tests)
        guide = GUIDE.read_text(encoding="utf-8")
        for expected in (
            "--run-fixed-synthetic-ollama-timing-probe", "127.0.0.1:11434",
            "PowerShell", "Pilot GO=NO", "1m", "no independent attestation",
        ):
            self.assertIn(expected, guide)


if __name__ == "__main__":
    unittest.main()

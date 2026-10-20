"""Always-on contract guard for explicit read-only Ollama inventory."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
CODE = ROOT / "scripts/pilot_local_ai_model_inventory.py"
TEST = ROOT / "scripts/tests/test_pilot_local_ai_model_inventory.py"
GUIDE = ROOT / "docs/operations/LOCAL_AI_MODEL_INVENTORY.md"


class LocalModelInventoryPolicy(unittest.TestCase):
    def test_only_fixed_loopback_read_no_arbitrary_paths_or_external_inference(self):
        text = CODE.read_text(encoding="utf-8")
        imports = set()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {
            "__future__", "http.client", "json", "re", "sys", "typing",
            "scripts.pilot_local_ai_synthetic_handoff",
        })
        for needle in (
            '_HOST = "127.0.0.1"',
            "_PORT = 11434",
            '_PATH = "/api/tags"',
            '"GET", _PATH',
            "_MAX_RESPONSE_BYTES = 65536",
            "response.read(_MAX_RESPONSE_BYTES + 1)",
            'args != ["--inspect-fixed-local-ollama-tag"]',
            '"model_artifact_independently_attested": False',
            '"model_execution_verified": False',
            '"network_egress_isolation_verified": False',
            '"pilot_accepted": False',
            'print("local_model_inventory_inspection_failed")',
        ):
            self.assertIn(needle, text)
        for forbidden in (
            'conn.request("POST"', '"POST",', "api/generate",
            "open(", "write_text(", "read_text(", "subprocess",
            "requests.", "OpenAI(", "get_ai_provider(", "DATABASE_URL",
        ):
            self.assertNotIn(forbidden, text)

    def test_mocked_negative_coverage_and_runbook_are_present(self):
        tests = TEST.read_text(encoding="utf-8")
        for named in (
            "test_local_tag_digest_reported_but_never_attested",
            "test_missing_model_is_no_go_without_other_inventory_disclosure",
            "test_malformed_ambiguous_or_fake_digest_rejected",
            "test_bad_http_status_or_payload_size_or_network_error_fails_closed",
            "test_cli_never_connects_without_exact_opt_in",
            "test_dynamic_error_message_never_leaked_to_cli",
        ):
            self.assertIn(named, tests)
        guide = GUIDE.read_text(encoding="utf-8")
        for needle in (
            "--inspect-fixed-local-ollama-tag",
            "127.0.0.1:11434",
            "Pilot GO=NO",
            "not independent attestation",
            "PowerShell",
        ):
            self.assertIn(needle, guide)


if __name__ == "__main__":
    unittest.main()

"""No-network regression tests for read-only localhost Ollama inventory."""
import json
import unittest
from unittest.mock import patch

from scripts import pilot_local_ai_model_inventory as inventory

DIGEST = "a" * 64


class FakeHTTPResponse:
    def __init__(self, raw, status=200):
        self._raw = raw
        self.status = status
        self.limit = None

    def read(self, limit):
        self.limit = limit
        return self._raw[:limit]


class FakeConnection:
    def __init__(self, raw, status=200, error=None):
        self.response = FakeHTTPResponse(raw, status=status)
        self.request_params = None
        self.closed = False
        self.error = error

    def request(self, *args, **kwargs):
        if self.error is not None:
            raise self.error
        self.request_params = (args, kwargs)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class LocalOllamaInventoryTests(unittest.TestCase):
    def _observe(self, data, status=200, error=None):
        raw = data if type(data) is bytes else json.dumps(data).encode("utf-8")
        con = FakeConnection(raw, status, error)
        observed = []

        def factory(host, port, *, timeout):
            observed.append((host, port, timeout))
            return con

        try:
            result = inventory.inspect_fixed_local_model_inventory(factory)
            return result, con, observed
        finally:
            self.assertEqual(observed, [("127.0.0.1", 11434, 5)])
            self.assertTrue(con.closed)
            if error is None:
                self.assertEqual(
                    con.request_params,
                    (("GET", "/api/tags"), {"headers": {"Accept": "application/json"}}),
                )

    def test_local_tag_digest_reported_but_never_attested(self):
        for digest in (DIGEST, "sha256:" + DIGEST):
            with self.subTest(digest=digest[:7]):
                report, conn, observed = self._observe({
                    "models": [
                        {"name": "unrelated-model", "digest": "NOT-EXPORTED"},
                        {"name": "qwen3:1.7b", "model": "qwen3:1.7b", "digest": digest},
                    ]
                })
                self.assertEqual(conn.response.limit, inventory._MAX_RESPONSE_BYTES + 1)
                self.assertEqual(report["observed_digest_sha256"], DIGEST)
                self.assertTrue(report["model_tag_observed"])
                for field in (
                    "observed_digest_source_attested",
                    "model_artifact_independently_attested",
                    "model_execution_verified",
                    "network_egress_isolation_verified",
                    "pilot_accepted",
                ):
                    self.assertIs(report[field], False)
                self.assertNotIn("unrelated-model", json.dumps(report))

    def test_missing_model_is_no_go_without_other_inventory_disclosure(self):
        report, _, _ = self._observe({
            "models": [{"name": "private-other-local-model", "digest": "hidden"}]
        })
        self.assertIs(report["model_tag_observed"], False)
        self.assertIsNone(report["observed_digest_sha256"])
        self.assertNotIn("private-other-local-model", json.dumps(report))

    def test_malformed_ambiguous_or_fake_digest_rejected(self):
        cases = [
            b"not-json",
            {"error": "PRIVATE-HOST-DIAGNOSTIC"},
            {"models": "not-a-list"},
            {"models": [{}] * 129},
            {"models": [{"name": "qwen3:1.7b", "digest": "a" * 63}]},
            {"models": [{"name": "qwen3:1.7b", "digest": "G" * 64}]},
            {"models": [{"name": "qwen3:1.7b", "model": "other", "digest": DIGEST}]},
            {"models": [
                {"name": "qwen3:1.7b", "digest": DIGEST},
                {"name": "qwen3:1.7b", "digest": DIGEST},
            ]},
        ]
        for data in cases:
            with self.subTest(case=str(data)[:50]):
                with self.assertRaises(inventory.LocalModelInventoryError):
                    self._observe(data)

    def test_bad_http_status_or_payload_size_or_network_error_fails_closed(self):
        with self.assertRaises(inventory.LocalModelInventoryError):
            self._observe({"models": []}, status=503)
        with self.assertRaises(inventory.LocalModelInventoryError):
            self._observe(b"x" * (inventory._MAX_RESPONSE_BYTES + 1))
        with self.assertRaises(inventory.LocalModelInventoryError):
            self._observe({"models": []}, error=ConnectionRefusedError("secret diagnostic"))

    def test_cli_never_connects_without_exact_opt_in(self):
        with patch.object(inventory, "inspect_fixed_local_model_inventory", side_effect=AssertionError("must not run")):
            for args in ([], ["--wrong"], ["--inspect-fixed-local-ollama-tag", "path"]):
                with patch("builtins.print") as printed:
                    self.assertEqual(inventory.main(args), 2)
                    printed.assert_called_once_with("local_model_inventory_explicit_opt_in_required")

    def test_cli_returns_safe_summary_without_proving_attestation(self):
        observed = {
            "model_tag_observed": True,
            "observed_digest_sha256": DIGEST,
            "model_artifact_independently_attested": False,
            "pilot_accepted": False,
        }
        with patch.object(inventory, "inspect_fixed_local_model_inventory", return_value=observed):
            with patch("builtins.print") as printed:
                self.assertEqual(inventory.main(["--inspect-fixed-local-ollama-tag"]), 0)
                printed.assert_called_once()
                result = json.loads(printed.call_args.args[0])
                self.assertFalse(result["pilot_accepted"])

    def test_dynamic_error_message_never_leaked_to_cli(self):
        with patch.object(inventory, "inspect_fixed_local_model_inventory",
                          side_effect=RuntimeError("VERY-PRIVATE-TEST-ONLY")):
            with patch("builtins.print") as printed:
                self.assertEqual(inventory.main(["--inspect-fixed-local-ollama-tag"]), 1)
                printed.assert_called_once_with("local_model_inventory_inspection_failed")


if __name__ == "__main__":
    unittest.main()

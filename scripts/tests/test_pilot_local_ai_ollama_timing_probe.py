"""No-network tests of fixed synthetic timing, privacy, and error boundaries."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from scripts import pilot_local_ai_ollama_timing_probe as probe


class FakeResponse:
    def __init__(self, *, status=200, payload=None, raw=None):
        self.status = status
        self.raw = raw if raw is not None else json.dumps(payload if payload is not None else {
            "model": "qwen3:1.7b", "done": True, "response": "PRIVATE GENERATED RESPONSE",
            "load_duration": 8_000_000_000, "prompt_eval_duration": 2_000_000_000,
            "eval_duration": 4_000_000_000, "total_duration": 14_000_000_000,
            "eval_count": 2,
        }).encode("utf-8")

    def read(self, _size):
        return self.raw


class FakeConnection:
    def __init__(self, response=None, problem=None):
        self.response = FakeResponse() if response is None else response
        self.problem = problem
        self.closed = False
        self.request_record = None

    def request(self, method, path, *, body, headers):
        if self.problem:
            raise self.problem
        self.request_record = (method, path, json.loads(body), headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class TimingProbeTests(unittest.TestCase):
    def test_exact_two_fixed_loopback_calls_never_return_text(self):
        sockets = [FakeConnection(), FakeConnection()]
        called = []

        def factory(host, port, timeout):
            called.append((host, port, timeout))
            return sockets[len(called)-1]

        result = probe.fixed_two_trial_observation(factory)
        self.assertTrue(result["all_trials_measured"])
        self.assertEqual(called, [("127.0.0.1", 11434, 90)] * 2)
        for s in sockets:
            self.assertTrue(s.closed)
            method, path, body, headers = s.request_record
            self.assertEqual((method, path), ("POST", "/api/generate"))
            self.assertEqual(body["model"], "qwen3:1.7b")
            self.assertEqual(body["keep_alive"], "1m")
            self.assertIs(body["think"], False)
            self.assertIs(body["stream"], False)
            self.assertEqual(body["options"]["num_predict"], 16)
            self.assertNotIn("customer", json.dumps(body).lower())
        serialized = json.dumps(result)
        self.assertNotIn("PRIVATE GENERATED RESPONSE", serialized)
        self.assertEqual(result["trials"][0]["load_ms_observed"], 8000)
        self.assertEqual(result["trials"][0]["eval_ms_observed"], 4000)
        self.assertFalse(result["pilot_accepted"])
        self.assertFalse(result["first_trial_known_cold"])
        self.assertFalse(result["second_trial_proven_warm"])

    def test_network_timeout_is_sanitized_and_second_trial_still_attempted(self):
        sockets = [FakeConnection(problem=TimeoutError("customer private path")), FakeConnection()]
        calls = []

        def factory(host, port, timeout):
            calls.append((host, port, timeout))
            return sockets[len(calls)-1]

        result = probe.fixed_two_trial_observation(factory)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(s.closed for s in sockets))
        self.assertFalse(result["all_trials_measured"])
        self.assertEqual(result["trials"][0]["rejection_category"], "local_runtime_unavailable")
        self.assertEqual(result["trials"][1]["status"], "measured")
        self.assertNotIn("private", str(result))

    def test_untrusted_timing_model_shape_and_oversized_response_fail_closed(self):
        bad = [
            FakeResponse(status=503),
            FakeResponse(raw=b"{"),
            FakeResponse(raw=b"x" * 65_537),
            FakeResponse(payload={"model": "wrong", "done": True, "response": "secret"}),
            FakeResponse(payload={"model": "qwen3:1.7b", "done": True, "response": "secret", "total_duration": True}),
        ]
        for response in bad:
            with self.subTest(status=response.status, size=len(response.raw)):
                sockets = [FakeConnection(response=response), FakeConnection()]
                def factory(host, port, timeout):
                    return sockets.pop(0)
                result = probe.fixed_two_trial_observation(factory)
                self.assertFalse(result["all_trials_measured"])
                self.assertEqual(result["trials"][0]["status"], "rejected")
                self.assertNotIn("secret", json.dumps(result))

    def test_cli_requires_exact_manual_flag_without_model_call(self):
        with patch.object(probe, "fixed_two_trial_observation", side_effect=AssertionError("DO NOT RUN")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = probe.main([])
            self.assertEqual(code, 2)
            self.assertEqual(output.getvalue().strip(), "local_ollama_timing_probe_explicit_opt_in_required")

    def test_cli_never_leaks_dynamic_exception_text(self):
        with patch.object(probe, "fixed_two_trial_observation", side_effect=RuntimeError("private data")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = probe.main(["--run-fixed-synthetic-ollama-timing-probe"])
            self.assertEqual(code, 1)
            self.assertEqual(output.getvalue().strip(), "local_ollama_timing_probe_failed")


if __name__ == "__main__":
    unittest.main()

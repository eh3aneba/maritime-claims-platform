"""Offline no-network regression coverage for an opt-in local three-case smoke."""
import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from app.ai.gateway.base import AIProviderUnavailable, AIResponse
from scripts.pilot_local_ai_hm_fixture_matrix import (
    deterministic_reference_candidate, scenario_names,
)
import scripts.pilot_local_ai_hm_loopback_smoke as smoke


class FakeProvider:
    name = "ollama_local"

    def __init__(self, *, bad_scenario: int = -1, disconnected: bool = False):
        self.calls = []
        self.bad_scenario = bad_scenario
        self.disconnected = disconnected

    def generate(self, request):
        assert request.metadata == {"synthetic_local_ai_test": True}
        assert request.task == "synthetic_hm_source_quote_review"
        assert request.input_text.count("| v1]") == 3
        assert "claim_id" not in request.metadata
        assert "document_id" not in request.metadata
        idx = len(self.calls)
        self.calls.append(request)
        if self.disconnected:
            raise AIProviderUnavailable("local_ai_unavailable")
        scenario = scenario_names()[idx]
        output = deterministic_reference_candidate(scenario)["items"]
        if self.bad_scenario == idx:
            output[0]["verbatim_excerpt"] = "Owner is negligent; insurer must pay."
        return AIResponse(
            provider="ollama_local",
            model="qwen3:1.7b",
            structured_output={"items": output},
        )


def test_all_fixed_cases_yield_only_counts_not_model_prose():
    fake = FakeProvider()
    result = smoke.run_fixed_three_scenario_smoke(fake)
    assert len(fake.calls) == 3
    assert result["all_accepted_for_human_review"] is True
    assert result["pilot_accepted"] is False
    assert result["model_digest_attested"] is False
    assert result["local_transport_attested"] is False
    assert result["expert_ground_truth_approved"] is False
    assert [r["scenario"] for r in result["scenarios"]] == list(scenario_names())
    assert all(r["quote_count"] == 3 and r["literal_baseline_match_count"] == 3
               for r in result["scenarios"])
    assert all(type(r["elapsed_ms_observed"]) is int and r["elapsed_ms_observed"] >= 0
               for r in result["scenarios"])
    output = json.dumps(result)
    for sensitive in ("negligent", "turbocharger alarm", "11:55", "Engine logs"):
        assert sensitive not in output


def test_one_hallucination_rejected_without_stopping_other_cases():
    fake = FakeProvider(bad_scenario=1)
    result = smoke.run_fixed_three_scenario_smoke(fake)
    assert len(fake.calls) == 3
    assert result["all_accepted_for_human_review"] is False
    assert [r["status"] for r in result["scenarios"]] == [
        "source_quotes_accepted_for_human_review",
        "rejected",
        "source_quotes_accepted_for_human_review",
    ]
    assert "negligent" not in str(result)


def test_unavailable_local_adapter_reports_safe_rejection_only():
    fake = FakeProvider(disconnected=True)
    result = smoke.run_fixed_three_scenario_smoke(fake)
    assert len(fake.calls) == 3
    assert result["all_accepted_for_human_review"] is False
    assert all(x["status"] == "rejected" for x in result["scenarios"])
    assert "local_ai_unavailable" not in str(result)


def test_wrong_provider_refused_without_model_call():
    fake = FakeProvider()
    fake.name = "openai"
    with pytest.raises(AIProviderUnavailable, match="local_ai_provider_not_allowed"):
        smoke.run_fixed_three_scenario_smoke(fake)
    assert fake.calls == []


def test_request_is_one_shot_fixed_literal_fixture_only():
    request = smoke.build_fixed_scenario_request("conflicting_alarm_times")
    assert "[S1 | reported_statement | v1]" in request.input_text
    assert "[S2 | reported_statement | v1]" in request.input_text
    assert "11:30" in request.input_text
    assert "11:55" in request.input_text
    assert request.output_schema["additionalProperties"] is False
    assert request.output_schema["properties"]["items"]["items"]["additionalProperties"] is False
    assert request.metadata == {"synthetic_local_ai_test": True}
    with pytest.raises(ValueError, match="unknown_synthetic_scenario"):
        smoke.build_fixed_scenario_request("real_customer_claim")


def test_cli_requires_explicit_opt_in_and_does_not_contact_provider(monkeypatch, capsys):
    def forbidden(*a, **k):
        raise AssertionError("model must not run without explicit flag")
    monkeypatch.setattr(smoke, "OllamaLocalExperimentalProvider", forbidden)
    assert smoke.main([]) == 2
    assert capsys.readouterr().out.strip() == "local_ai_explicit_synthetic_opt_in_required"


def test_cli_with_opt_in_prints_only_safe_summary(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "OllamaLocalExperimentalProvider", lambda **_: FakeProvider())
    assert smoke.main(["--run-fixed-synthetic-ollama"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["all_accepted_for_human_review"] is True
    assert result["pilot_accepted"] is False
    assert "Abnormal vibration" not in json.dumps(result)


def test_cli_unexpected_errors_hidden_without_stack_or_source_text(monkeypatch, capsys):
    def failed_provider(**kwargs):
        raise RuntimeError("Sensitive invented details must not appear")
    monkeypatch.setattr(smoke, "OllamaLocalExperimentalProvider", failed_provider)
    assert smoke.main(["--run-fixed-synthetic-ollama"]) == 1
    assert capsys.readouterr().out.strip() == "local_ai_synthetic_smoke_failed"


def test_malformed_provider_response_is_rejected_and_other_scenarios_continue():
    class MalformedResponse(FakeProvider):
        def generate(self, request):
            if not self.calls:
                self.calls.append(request)
                return None
            return super().generate(request)

    fake = MalformedResponse()
    result = smoke.run_fixed_three_scenario_smoke(fake)
    assert len(fake.calls) == 3
    assert result["all_accepted_for_human_review"] is False
    assert result["scenarios"][0]["status"] == "rejected"
    assert all(x["status"] == "source_quotes_accepted_for_human_review"
               for x in result["scenarios"][1:])

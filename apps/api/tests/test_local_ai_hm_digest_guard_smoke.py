"""Mock-only tests for strict pre/post Ollama digest drift observation."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.ai.gateway.base import AIResponse
from scripts.pilot_local_ai_hm_fixture_matrix import (
    deterministic_reference_candidate, scenario_names,
)
import scripts.pilot_local_ai_hm_digest_guard_smoke as guarded

FIRST = "a" * 64
SECOND = "b" * 64


def observed(digest=FIRST, **changes):
    result = {
        "scope": "synthetic_local_pc_inventory_only",
        "registry": "ollama_loopback_tag_listing",
        "expected_model_tag": "qwen3:1.7b",
        "model_tag_observed": True,
        "observed_digest_sha256": digest,
        "observed_digest_source_attested": False,
        "model_artifact_independently_attested": False,
        "model_execution_verified": False,
        "network_egress_isolation_verified": False,
        "human_review_completed": False,
        "pilot_accepted": False,
    }
    result.update(changes)
    return result


class FakeProvider:
    name = "ollama_local"

    def __init__(self, *, drop_conflict_at=-1, split_context_at=-1):
        self.calls = []
        self.drop_conflict_at = drop_conflict_at
        self.split_context_at = split_context_at

    def generate(self, request):
        assert request.task == "synthetic_hm_source_quote_review"
        assert request.metadata == {"synthetic_local_ai_test": True}
        index = len(self.calls)
        self.calls.append(request)
        name = scenario_names()[index % 3]
        quotes = deterministic_reference_candidate(name)["items"]
        if index == self.split_context_at and name == "missing_engine_records":
            quotes = quotes[:2] + [
                {"kind": "intake_status", "source_id": "S3",
                 "source_version": "v1", "verbatim_excerpt": "NOT BEEN SUPPLIED"},
                {"kind": "intake_status", "source_id": "S3",
                 "source_version": "v1", "verbatim_excerpt": "existence is unknown"},
            ]
        if index == self.drop_conflict_at:
            quotes = [item for item in quotes if item["source_id"] != "S2"]
        return AIResponse(
            provider="ollama_local", model="qwen3:1.7b",
            structured_output={"items": quotes},
        )


def test_exact_preflight_nine_requests_postflight_order():
    provider = FakeProvider()
    events = []

    def inventory():
        events.append(("snapshot", len(provider.calls)))
        return observed()

    result = guarded.run_fixed_digest_guarded_smoke(provider, inventory)
    assert events == [("snapshot", 0), ("snapshot", 9)]
    assert len(provider.calls) == 9
    assert result["local_tag_digest_same_before_after"] is True
    assert result["guarded_observation_accepted_for_human_review"] is True
    assert all(x["accepted_rounds"] == 3 for x in result["scenarios"])
    assert all(x["context_complete_rounds"] == 3 for x in result["scenarios"])
    assert all(x["context_pairs_missing_total"] == 0 for x in result["scenarios"])
    for flag in (
        "model_digest_attested", "model_execution_independently_attested",
        "model_artifact_independently_attested", "network_egress_isolation_verified",
        "repeatability_proven", "expert_ground_truth_approved",
        "human_review_completed", "pilot_accepted",
    ):
        assert result[flag] is False
    output = json.dumps(result)
    for secret in (FIRST, "Turbocharger damage", "NOT BEEN SUPPLIED", "11:55"):
        assert secret not in output


def test_digest_guard_sanitizes_non_gate_context_warning():
    provider = FakeProvider(split_context_at=4)
    result = guarded.run_fixed_digest_guarded_smoke(provider, lambda: observed())
    assert len(provider.calls) == 9
    assert result["local_tag_digest_same_before_after"] is True
    assert result["all_rounds_source_quotes_accepted_for_review"] is True
    assert result["guarded_observation_accepted_for_human_review"] is True
    assert result["scenarios"][1]["context_complete_rounds"] == 2
    assert result["scenarios"][1]["context_incomplete_rounds"] == 1
    assert result["scenarios"][1]["context_pairs_missing_total"] == 1
    assert result["context_preservation_expert_verified"] is False
    assert "NOT BEEN SUPPLIED" not in json.dumps(result)


@pytest.mark.parametrize("field,bad", (
    ("context_complete_rounds", -1),
    ("context_not_evaluated_rounds", True),
    ("context_pairs_missing_total", 10),
    ("context_incomplete_rounds", "1"),
))
def test_digest_guard_refuses_invalid_context_summary(monkeypatch, field, bad):
    real = guarded.run_three_fixed_rounds

    def malformed(provider):
        data = real(provider)
        data["scenarios"][0][field] = bad
        return data

    monkeypatch.setattr(guarded, "run_three_fixed_rounds", malformed)
    with pytest.raises(ValueError, match="^invalid_local_repeat_report$"):
        guarded.run_fixed_digest_guarded_smoke(FakeProvider(), lambda: observed())


def test_digest_changed_after_nine_requests_denies_guarded_success():
    provider = FakeProvider()
    values = iter((observed(FIRST), observed(SECOND)))
    result = guarded.run_fixed_digest_guarded_smoke(provider, lambda: next(values))
    assert len(provider.calls) == 9
    assert result["all_rounds_source_quotes_accepted_for_review"] is True
    assert result["local_tag_digest_same_before_after"] is False
    assert result["guarded_observation_accepted_for_human_review"] is False
    assert FIRST not in str(result) and SECOND not in str(result)


def test_missing_or_untrusted_preflight_never_calls_model():
    for before in (
        observed(model_tag_observed=False),
        observed(observed_digest_sha256="not-a-digest"),
        observed(model_artifact_independently_attested=True),
        observed(expected_model_tag="foreign-model"),
        observed(digest=SECOND, registry="tampered"),
        {},
    ):
        provider = FakeProvider()
        with pytest.raises(ValueError, match="invalid_local_model_observation"):
            guarded.run_fixed_digest_guarded_smoke(provider, lambda: before)
        assert provider.calls == []


def test_postflight_missing_or_untrusted_fails_closed_without_success():
    provider = FakeProvider()
    values = iter((observed(), observed(model_tag_observed=False)))
    with pytest.raises(ValueError, match="invalid_local_model_observation"):
        guarded.run_fixed_digest_guarded_smoke(provider, lambda: next(values))
    assert len(provider.calls) == 9


def test_source_quote_incomplete_cannot_be_reported_as_guarded_success():
    provider = FakeProvider(drop_conflict_at=8)
    result = guarded.run_fixed_digest_guarded_smoke(provider, lambda: observed())
    assert result["local_tag_digest_same_before_after"] is True
    assert result["all_rounds_source_quotes_accepted_for_review"] is False
    assert result["guarded_observation_accepted_for_human_review"] is False
    assert result["scenarios"][2]["incomplete_rounds"] == 1


def test_cli_requires_one_exact_manual_flag_and_never_connects_without_it(monkeypatch, capsys):
    monkeypatch.setattr(guarded, "OllamaLocalExperimentalProvider",
                        lambda **_: pytest.fail("no constructor without flag"))
    for args in ([], ["--wrong"], ["--run-fixed-synthetic-ollama-digest-guard", "path"]):
        assert guarded.main(args) == 2
        assert capsys.readouterr().out.strip() == "local_model_digest_guard_explicit_opt_in_required"


def test_cli_sanitizes_unexpected_inventory_exceptions(monkeypatch, capsys):
    monkeypatch.setattr(guarded, "OllamaLocalExperimentalProvider", lambda **_: FakeProvider())

    def error():
        raise RuntimeError("PRIVATE-HOST-DIAGNOSTIC")

    monkeypatch.setattr(guarded, "inspect_fixed_local_model_inventory", error)
    assert guarded.main(["--run-fixed-synthetic-ollama-digest-guard"]) == 1
    assert capsys.readouterr().out.strip() == "local_model_digest_guard_failed"


def test_cli_reports_only_bounded_results_when_digest_changes(monkeypatch, capsys):
    provider = FakeProvider()
    monkeypatch.setattr(guarded, "OllamaLocalExperimentalProvider", lambda **_: provider)
    values = iter((observed(FIRST), observed(SECOND)))
    monkeypatch.setattr(guarded, "inspect_fixed_local_model_inventory", lambda: next(values))
    assert guarded.main(["--run-fixed-synthetic-ollama-digest-guard"]) == 1
    raw = capsys.readouterr().out
    result = json.loads(raw)
    assert result["local_tag_digest_same_before_after"] is False
    assert result["pilot_accepted"] is False
    assert FIRST not in raw and SECOND not in raw
    assert len(provider.calls) == 9

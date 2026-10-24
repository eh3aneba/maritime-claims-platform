"""No-network unit checks for three-round localhost synthetic smoke."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.ai.gateway.base import AIProviderUnavailable, AIResponse
from scripts.pilot_local_ai_hm_fixture_matrix import (
    deterministic_reference_candidate, scenario_names,
)
import scripts.pilot_local_ai_hm_repeat_smoke as repeat


class SyntheticProvider:
    name = "ollama_local"

    def __init__(self, *, incomplete_at: int = -1, rejected_at: int = -1,
                 split_context_at: int = -1, unavailable: bool = False):
        self.calls = []
        self.incomplete_at = incomplete_at
        self.rejected_at = rejected_at
        self.split_context_at = split_context_at
        self.unavailable = unavailable

    def generate(self, request):
        assert request.metadata == {"synthetic_local_ai_test": True}
        assert request.task == "synthetic_hm_source_quote_review"
        assert request.input_text.count("| v1]") == 3
        index = len(self.calls)
        self.calls.append(request)
        if self.unavailable:
            raise AIProviderUnavailable("local_ai_unavailable")
        name = scenario_names()[index % 3]
        items = deterministic_reference_candidate(name)["items"]
        if index == self.incomplete_at:
            items[-1]["verbatim_excerpt"] = (
                "Synthetic intake: Engine logs for the previous ten days"
            )
        if index == self.split_context_at and name == "missing_engine_records":
            # Still passes all four literal anchors, but the status and its
            # uncertainty qualifier do not co-occur in one source quote.
            items = items[:2] + [
                {"kind": "intake_status", "source_id": "S3",
                 "source_version": "v1", "verbatim_excerpt": "NOT BEEN SUPPLIED"},
                {"kind": "intake_status", "source_id": "S3",
                 "source_version": "v1", "verbatim_excerpt": "existence is unknown"},
            ]
        if index == self.rejected_at:
            items[0]["verbatim_excerpt"] = "The workshop confirmed owner negligence."
        return AIResponse(
            provider="ollama_local", model="qwen3:1.7b",
            structured_output={"items": items},
        )


def test_exact_nine_calls_and_bounded_success_metrics_without_prose():
    fake = SyntheticProvider()
    result = repeat.run_three_fixed_rounds(fake)
    assert len(fake.calls) == 9
    assert result["rounds_observed"] == 3
    assert result["fixed_scenarios_per_round"] == 3
    assert result["all_rounds_source_quotes_accepted_for_review"] is True
    assert [x["scenario"] for x in result["scenarios"]] == list(scenario_names())
    for row in result["scenarios"]:
        assert row["accepted_rounds"] == 3
        assert row["incomplete_rounds"] == row["rejected_rounds"] == 0
        assert row["context_complete_rounds"] == 3
        assert row["context_incomplete_rounds"] == 0
        assert row["context_not_evaluated_rounds"] == 0
        assert row["context_pairs_missing_total"] == 0
        assert 0 <= row["min_elapsed_ms_observed"] <= row["max_elapsed_ms_observed"]
    for forbidden in ("Turbocharger damage", "NOT BEEN SUPPLIED", "11:55", "negligence"):
        assert forbidden not in json.dumps(result)
    for field in (
        "pilot_accepted", "repeatability_proven", "model_digest_attested",
        "model_execution_independently_attested", "expert_ground_truth_approved",
        "human_review_completed", "production_authorized",
    ):
        assert result[field] is False


def test_partial_and_hallucinated_rounds_never_report_full_acceptance():
    fake = SyntheticProvider(incomplete_at=4, rejected_at=8)
    result = repeat.run_three_fixed_rounds(fake)
    assert len(fake.calls) == 9
    assert result["all_rounds_source_quotes_accepted_for_review"] is False
    complete, missing, conflicting = result["scenarios"]
    assert complete["accepted_rounds"] == 3
    assert (missing["accepted_rounds"], missing["incomplete_rounds"], missing["rejected_rounds"]) == (2, 1, 0)
    assert (conflicting["accepted_rounds"], conflicting["incomplete_rounds"], conflicting["rejected_rounds"]) == (2, 0, 1)
    assert "negligence" not in json.dumps(result)
    assert conflicting["context_not_evaluated_rounds"] == 1


def test_quote_gate_success_can_coexist_with_context_diagnostic_warning():
    fake = SyntheticProvider(split_context_at=4)
    result = repeat.run_three_fixed_rounds(fake)
    assert len(fake.calls) == 9
    assert result["all_rounds_source_quotes_accepted_for_review"] is True
    rows = result["scenarios"]
    assert rows[1]["accepted_rounds"] == 3
    assert rows[1]["context_complete_rounds"] == 2
    assert rows[1]["context_incomplete_rounds"] == 1
    assert rows[1]["context_not_evaluated_rounds"] == 0
    assert rows[1]["context_pairs_missing_total"] == 1
    assert all(x["context_incomplete_rounds"] == 0 for x in (rows[0], rows[2]))
    assert result["context_preservation_expert_verified"] is False
    assert result["pilot_accepted"] is False
    assert "NOT BEEN SUPPLIED" not in json.dumps(result)


def test_disconnected_localhost_is_safe_and_not_counted_as_success():
    fake = SyntheticProvider(unavailable=True)
    result = repeat.run_three_fixed_rounds(fake)
    assert len(fake.calls) == 9
    assert result["all_rounds_source_quotes_accepted_for_review"] is False
    assert all(x["rejected_rounds"] == 3 for x in result["scenarios"])
    assert all(x["context_not_evaluated_rounds"] == 3 for x in result["scenarios"])
    assert all(x["context_pairs_missing_total"] == 0 for x in result["scenarios"])
    assert "local_ai_unavailable" not in json.dumps(result)



 
@pytest.mark.parametrize("shape", (
    "empty",
    "one_missing",
    "reverse_order",
    "not_a_list",
    "non_dict_row",
    "duplicated_scenario",
    "extra_record",
    "unknown_scenario",
))
def test_three_round_report_rejects_malformed_scenario_structure(monkeypatch, shape):
    rows = [
        {"scenario": name, "status": "rejected", "elapsed_ms_observed": 0}
        for name in scenario_names()
    ]
    if shape == "empty":
        rows = []
    elif shape == "one_missing":
        rows = rows[:-1]
    elif shape == "reverse_order":
        rows = list(reversed(rows))
    elif shape == "not_a_list":
        rows = tuple(rows)
    elif shape == "non_dict_row":
        rows[0] = None
    elif shape == "duplicated_scenario":
        rows[1]["scenario"] = rows[0]["scenario"]
    elif shape == "extra_record":
        rows.append({"scenario": "unexpected_case", "status": "rejected", "elapsed_ms_observed": 0})
    elif shape == "unknown_scenario":
        rows[0]["scenario"] = "unapproved_synthetic_case"
    monkeypatch.setattr(repeat, "run_fixed_three_scenario_smoke", lambda _provider: {
        "scenarios": rows,
    })
    with pytest.raises(ValueError, match="^invalid_synthetic_round_shape$"):
        repeat.run_three_fixed_rounds(SyntheticProvider())


@pytest.mark.parametrize("status,elapsed", (
    ("unexpected_status", 0),
    ("rejected", -1),
    ("rejected", True),
    ("rejected", 3_600_001),
    (None, 0),
    ("source_quotes_accepted_for_human_review", 1.5),
))
def test_repeat_rounds_fail_closed_on_invalid_status_or_timing(monkeypatch, status, elapsed):
    names = scenario_names()
    def malformed_round(_provider):
        return {
            "scenarios": [
                {
                    "scenario": name,
                    "status": status if index == 0 else "rejected",
                    "elapsed_ms_observed": elapsed if index == 0 else 0,
                }
                for index, name in enumerate(names)
            ],
        }

    monkeypatch.setattr(repeat, "run_fixed_three_scenario_smoke", malformed_round)
    with pytest.raises(ValueError, match="^invalid_synthetic_round_value$"):
        repeat.run_three_fixed_rounds(SyntheticProvider())



@pytest.mark.parametrize("bad_value", (-1, 4, True, "3", None))
def test_malformed_context_counters_fail_closed(monkeypatch, bad_value):
    fake = SyntheticProvider()
    original = repeat.run_fixed_three_scenario_smoke

    def corrupted(provider):
        observation = original(provider)
        observation["scenarios"][0]["context_pairs_same_excerpt_missing"] = bad_value
        return observation

    monkeypatch.setattr(repeat, "run_fixed_three_scenario_smoke", corrupted)
    with pytest.raises(ValueError, match="^invalid_synthetic_context_observation$"):
        repeat.run_three_fixed_rounds(fake)


def test_explicit_opt_in_required_before_constructing_provider(monkeypatch, capsys):
    def forbidden(**kwargs):
        raise AssertionError("should not invoke even local provider")
    monkeypatch.setattr(repeat, "OllamaLocalExperimentalProvider", forbidden)
    for args in ([], ["--wrong"], ["--run-fixed-synthetic-ollama"], ["--run-fixed-synthetic-ollama-repeat-3", "secret"]):
        assert repeat.main(args) == 2
        assert capsys.readouterr().out.strip() == "local_ai_explicit_synthetic_repeat_opt_in_required"


def test_opt_in_cli_emits_counts_only_and_safely_exits(monkeypatch, capsys):
    p = SyntheticProvider(incomplete_at=4)
    monkeypatch.setattr(repeat, "OllamaLocalExperimentalProvider", lambda **kwargs: p)
    assert repeat.main(["--run-fixed-synthetic-ollama-repeat-3"]) == 1
    captured = capsys.readouterr().out
    report = json.loads(captured)
    assert len(p.calls) == 9
    assert report["scenarios"][1]["incomplete_rounds"] == 1
    assert report["pilot_accepted"] is False
    assert "11:55" not in captured


def test_successful_cli_is_not_pilot_go(monkeypatch, capsys):
    p = SyntheticProvider()
    monkeypatch.setattr(repeat, "OllamaLocalExperimentalProvider", lambda **kwargs: p)
    assert repeat.main(["--run-fixed-synthetic-ollama-repeat-3"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["all_rounds_source_quotes_accepted_for_review"] is True
    assert report["pilot_accepted"] is False
    assert report["repeatability_proven"] is False


def test_unexpected_provider_error_never_leaks_data(monkeypatch, capsys):
    def failed(**kwargs):
        raise RuntimeError("PRIVATE-TEST-ONLY-exception-and-mock")
    monkeypatch.setattr(repeat, "OllamaLocalExperimentalProvider", failed)
    assert repeat.main(["--run-fixed-synthetic-ollama-repeat-3"]) == 1
    assert capsys.readouterr().out.strip() == "local_ai_synthetic_repeat_smoke_failed"


def test_injected_malformed_round_fails_closed_without_dumping_model(monkeypatch, capsys):
    monkeypatch.setattr(repeat, "OllamaLocalExperimentalProvider", lambda **_: SyntheticProvider())
    monkeypatch.setattr(repeat, "run_fixed_three_scenario_smoke", lambda provider: {
        "scenarios": [{"scenario": "complete_records", "status": "garbage", "elapsed_ms_observed": 0}]
    })
    assert repeat.main(["--run-fixed-synthetic-ollama-repeat-3"]) == 1
    assert capsys.readouterr().out.strip() == "local_ai_synthetic_repeat_smoke_failed"

"""Deterministic offline regressions for all three synthetic H&M cases."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from scripts.pilot_local_ai_source_gate import LocalAISourceGateError
from scripts.pilot_local_ai_hm_fixture_matrix import (
    deterministic_reference_candidate, evaluate_synthetic_scenario,
    scenario_names, synthetic_source_catalog,
)


@pytest.mark.parametrize("scenario", (
    "complete_records", "missing_engine_records", "conflicting_alarm_times",
))
def test_reference_baseline_matches_only_code_owned_quotes(scenario):
    candidate = deterministic_reference_candidate(scenario)
    result = evaluate_synthetic_scenario(scenario, candidate)
    assert result == {
        "scope": "synthetic_development_only",
        "scenario": scenario,
        "validated_quote_count": 3,
        "reference_quote_count": 3,
        "reference_match_count": 3,
        "reference_missing_count": 0,
        "other_source_backed_quote_count": 0,
        "reference_expert_approved": False,
        "model_digest_attested": False,
        "real_model_executed": False,
        "human_review_required": True,
        "authoritative_fact_updates": False,
        "coverage_or_liability_decisions": False,
        "pilot_accepted": False,
    }
    assert not any(x in str(result) for x in (
        "Turbocharger damage", "engineer statement", "maintenance records"
    ))


def test_exact_scenario_set_and_source_copy_not_mutable():
    assert scenario_names() == (
        "complete_records", "missing_engine_records", "conflicting_alarm_times"
    )
    source = synthetic_source_catalog("missing_engine_records")
    source["S3"]["body"] = "Forged: log never existed."
    original = synthetic_source_catalog("missing_engine_records")
    assert "NOT BEEN SUPPLIED" in original["S3"]["body"]
    assert "existence is unknown" in original["S3"]["body"]


def test_conflicting_accounts_remain_separate_and_unresolved():
    source = synthetic_source_catalog("conflicting_alarm_times")
    assert "11:30" in source["S1"]["body"]
    assert "11:55" in source["S2"]["body"]
    candidate = deterministic_reference_candidate("conflicting_alarm_times")
    assert {x["source_id"] for x in candidate["items"]} == {"S1", "S2", "S3"}
    assert evaluate_synthetic_scenario("conflicting_alarm_times", candidate)[
        "coverage_or_liability_decisions"
    ] is False


@pytest.mark.parametrize("scenario", (
    None, "", False, 0, "actual_claim", [], "COMPLETE_RECORDS",
))
def test_never_accept_external_or_unlisted_scenario(scenario):
    with pytest.raises(LocalAISourceGateError, match="unknown_synthetic_scenario"):
        synthetic_source_catalog(scenario)


@pytest.mark.parametrize("invented", (
    "Engine logs do not exist, proving poor maintenance.",
    "The engineer confirmed negligence and H&M exclusion.",
    "The workshop report proves causation and approves settlement.",
))
def test_invented_neglect_coverage_or_absence_cannot_be_attributed(invented):
    scenario = "missing_engine_records"
    candidate = deterministic_reference_candidate(scenario)
    candidate["items"][0]["verbatim_excerpt"] = invented
    with pytest.raises(LocalAISourceGateError, match="unsupported_quote"):
        evaluate_synthetic_scenario(scenario, candidate)


@pytest.mark.parametrize("key,value", (
    ("model_id", "openai"),
    ("model_digest", "a" * 64),
    ("prompt_version", "changed-prompt-v2"),
))
def test_model_identity_and_prompt_cannot_claim_attestation(key, value):
    candidate = deterministic_reference_candidate("complete_records")
    candidate[key] = value
    with pytest.raises(LocalAISourceGateError, match="synthetic_model_metadata_mismatch"):
        evaluate_synthetic_scenario("complete_records", candidate)


def test_extra_source_backed_quote_is_not_an_expert_validated_reference():
    scenario = "missing_engine_records"
    candidate = deterministic_reference_candidate(scenario)
    candidate["items"][2]["verbatim_excerpt"] = "Engine logs for the previous ten days"
    result = evaluate_synthetic_scenario(scenario, candidate)
    assert result["reference_match_count"] == 2
    assert result["reference_missing_count"] == 1
    assert result["other_source_backed_quote_count"] == 1
    assert result["reference_expert_approved"] is False


def test_input_unchanged_and_source_lineage_reclassification_rejected():
    scenario = "conflicting_alarm_times"
    candidate = deterministic_reference_candidate(scenario)
    before = deepcopy(candidate)
    evaluate_synthetic_scenario(scenario, candidate)
    assert candidate == before
    candidate["items"][0]["kind"] = "event_notice"
    with pytest.raises(LocalAISourceGateError, match="source_lineage_mismatch"):
        evaluate_synthetic_scenario(scenario, candidate)



@pytest.mark.parametrize("scenario", (
    "complete_records", "missing_engine_records", "conflicting_alarm_times",
))
def test_unknown_source_id_is_rejected_in_all_synthetic_hm_scenarios(scenario):
    candidate = deterministic_reference_candidate(scenario)
    candidate["items"][0]["source_id"] = "S99"
    with pytest.raises(LocalAISourceGateError, match="^unknown_source$"):
        evaluate_synthetic_scenario(scenario, candidate)


@pytest.mark.parametrize("scenario", (
    "complete_records", "missing_engine_records", "conflicting_alarm_times",
))
def test_duplicate_quote_is_rejected_in_all_synthetic_hm_scenarios(scenario):
    candidate = deterministic_reference_candidate(scenario)
    candidate["items"].append(deepcopy(candidate["items"][0]))
    with pytest.raises(LocalAISourceGateError, match="^duplicate_quote$"):
        evaluate_synthetic_scenario(scenario, candidate)


def test_extra_claim_decision_is_not_accepted():
    candidate = deterministic_reference_candidate("complete_records")
    candidate["coverage"] = "approved"
    with pytest.raises(LocalAISourceGateError, match="invalid_candidate"):
        evaluate_synthetic_scenario("complete_records", candidate)

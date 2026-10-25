"""Mock-only synthetic post-blind quote reconstruction and leak prevention."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.ai.gateway.base import AIResponse, AIProviderUnavailable
from scripts.pilot_local_ai_hm_fixture_matrix import (
    deterministic_reference_candidate, scenario_names, synthetic_source_catalog,
)
from scripts import pilot_local_ai_hm_postblind_model_quotes as viewer


class FakeLocalProvider:
    name = "ollama_local"

    def __init__(self, *, invalid_at=-1, incomplete_at=-1, split_context_at=-1,
                 unavailable_at=-1, malformed_at=-1):
        self.calls = []
        self.invalid_at = invalid_at
        self.incomplete_at = incomplete_at
        self.split_context_at = split_context_at
        self.unavailable_at = unavailable_at
        self.malformed_at = malformed_at

    def generate(self, request):
        assert request.metadata == {"synthetic_local_ai_test": True}
        assert request.task == "synthetic_hm_source_quote_review"
        assert "claim_id" not in request.metadata
        assert "document_id" not in request.metadata
        i = len(self.calls)
        self.calls.append(request)
        if i == self.unavailable_at:
            raise AIProviderUnavailable("local_ai_unavailable")
        if i == self.malformed_at:
            return None
        name = scenario_names()[i]
        quotes = deterministic_reference_candidate(name)["items"]
        if i == self.invalid_at:
            quotes[0]["verbatim_excerpt"] = "Insurer must pay; PRIVATE-UNTRUSTED-TEXT"
        if i == self.incomplete_at:
            quotes[2]["verbatim_excerpt"] = "Synthetic intake"
        if i == self.split_context_at:
            assert name == "missing_engine_records"
            quotes = quotes[:2] + [
                {"kind": "intake_status", "source_id": "S3",
                 "source_version": "v1", "verbatim_excerpt": "NOT BEEN SUPPLIED"},
                {"kind": "intake_status", "source_id": "S3",
                 "source_version": "v1", "verbatim_excerpt": "existence is unknown"},
            ]
        return AIResponse(
            provider="ollama_local", model="qwen3:1.7b",
            structured_output={"items": quotes},
        )


def test_source_only_reconstruction_three_cases_and_no_approval():
    fake = FakeLocalProvider()
    report = viewer.run_fixed_postblind_synthetic_quote_view(fake)
    assert len(fake.calls) == 3
    assert report["all_source_quotes_valid_for_review"] is True
    assert [c["case_code"] for c in report["cases"]] == ["CASE-01", "CASE-02", "CASE-03"]
    for field in (
        "phase_one_packet_digest_independently_attested",
        "independent_reference_frozen_verified", "expert_labels_collected",
        "expert_semantic_review_completed", "model_execution_independently_attested",
        "model_digest_attested", "network_egress_isolation_verified",
        "real_claims_processed", "coverage_or_liability_decisions", "pilot_accepted",
    ):
        assert report[field] is False
    for name, item in zip(scenario_names(), report["cases"]):
        assert item["status"] == "source_quotes_accepted_for_human_review"
        source_catalog = synthetic_source_catalog(name)
        for quote in item["model_selected_source_excerpts"]:
            original = source_catalog[quote["source_id"]]
            assert quote["invented_source_excerpt"] == original["body"][
                quote["source_offset_start"]:quote["source_offset_end"]
            ]
            assert quote["source_version"] == original["version"]
        assert item["expert_semantic_review_completed"] is False


def test_unsupported_model_text_never_reaches_printable_output():
    fake = FakeLocalProvider(invalid_at=1)
    report = viewer.run_fixed_postblind_synthetic_quote_view(fake)
    assert len(fake.calls) == 3
    assert report["all_source_quotes_valid_for_review"] is False
    assert report["cases"][1]["status"] == "rejected"
    assert report["cases"][1]["rejection_category"] == "source_quote_rejected"
    assert "model_selected_source_excerpts" not in report["cases"][1]
    assert "PRIVATE-UNTRUSTED-TEXT" not in json.dumps(report)


def test_partial_valid_quote_may_be_reviewed_but_never_marked_complete():
    fake = FakeLocalProvider(incomplete_at=1)
    report = viewer.run_fixed_postblind_synthetic_quote_view(fake)
    assert len(fake.calls) == 3
    case = report["cases"][1]
    assert case["status"] == "source_quotes_incomplete_for_review"
    assert case["critical_literal_coverage_observed"] is False
    assert len(case["model_selected_source_excerpts"]) == 3
    assert report["all_source_quotes_valid_for_review"] is False


def test_source_backed_quote_with_separated_uncertainty_is_reported():
    fake = FakeLocalProvider(split_context_at=1)
    report = viewer.run_fixed_postblind_synthetic_quote_view(fake)
    case = report["cases"][1]
    assert case["status"] == "source_quotes_accepted_for_human_review"
    assert case["context_pairs_same_excerpt_missing"] == 1
    assert len(case["model_selected_source_excerpts"]) == 4
    assert report["pilot_accepted"] is False


@pytest.mark.parametrize("cause", ("unavailable", "malformed"))
def test_runtime_failure_never_exposes_model_text(cause):
    fake = FakeLocalProvider(
        unavailable_at=0 if cause == "unavailable" else -1,
        malformed_at=0 if cause == "malformed" else -1,
    )
    report = viewer.run_fixed_postblind_synthetic_quote_view(fake)
    assert len(fake.calls) == 3
    first = report["cases"][0]
    assert first["status"] == "rejected"
    assert first["rejection_category"] in ("local_runtime_unavailable", "invalid_model_response")
    assert "model_selected_source_excerpts" not in first


def test_wrong_provider_refused_before_model():
    fake = FakeLocalProvider()
    fake.name = "openai"
    with pytest.raises(AIProviderUnavailable, match="local_ai_provider_not_allowed"):
        viewer.run_fixed_postblind_synthetic_quote_view(fake)
    assert fake.calls == []


def test_phase_one_forged_blind_review_is_rejected_before_model(monkeypatch):
    fake = FakeLocalProvider()
    orig = viewer.fixed_neutral_blind_hm_phase_one_packet
    def forged():
        data = orig()
        data["review_completed"] = True
        return data
    monkeypatch.setattr(viewer, "fixed_neutral_blind_hm_phase_one_packet", forged)
    with pytest.raises(ValueError, match="untrusted_synthetic_phase_one_packet"):
        viewer.run_fixed_postblind_synthetic_quote_view(fake)
    assert fake.calls == []


def test_cli_requires_exact_flag_and_hides_unexpected_exceptions(monkeypatch, capsys):
    def boom(**kwargs):
        raise RuntimeError("PRIVATE-UNTRUSTED-ERROR")
    monkeypatch.setattr(viewer, "OllamaLocalExperimentalProvider", boom)
    for args in ([], ["--bad"], ["--reveal-fixed-synthetic-ollama-quotes-for-postblind-review", "path"]):
        assert viewer.main(args) == 2
        assert capsys.readouterr().out.strip() == "postblind_synthetic_hm_explicit_opt_in_required"
    assert viewer.main(["--reveal-fixed-synthetic-ollama-quotes-for-postblind-review"]) == 1
    assert capsys.readouterr().out.strip() == "postblind_synthetic_hm_quote_view_unavailable"


def test_manual_cli_emits_reconstructed_source_slices_only(monkeypatch, capsys):
    monkeypatch.setattr(viewer, "OllamaLocalExperimentalProvider",
                        lambda **_: FakeLocalProvider())
    assert viewer.main(["--reveal-fixed-synthetic-ollama-quotes-for-postblind-review"]) == 0
    raw = capsys.readouterr().out
    doc = json.loads(raw)
    assert doc["all_source_quotes_valid_for_review"] is True
    assert doc["independent_reference_frozen_verified"] is False
    assert "source_offset_start" in raw


def test_invalid_source_version_never_reaches_review():
    class WrongVersion(FakeLocalProvider):
        def generate(self, request):
            resp = super().generate(request)
            resp.structured_output["items"][0]["source_version"] = "v2"
            return resp
    report = viewer.run_fixed_postblind_synthetic_quote_view(WrongVersion())
    assert all(x["status"] == "rejected" for x in report["cases"])

"""Synthetic-only negative controls for #752 local H&M source custody."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pilot_local_ai_source_gate import (
    SCHEMA, LocalAISourceGateError, evaluate_synthetic_source_quotes,
)


def synthetic_fixture():
    sources = {
        "S1": {
            "kind": "event_notice", "version": "v1",
            "body": "Owner notification: Turbocharger damage reportedly occurred on 16 July 2025.",
        },
        "S2": {
            "kind": "reported_statement", "version": "v1",
            "body": "Chief Engineer reported abnormal vibration and high exhaust temperature before shutdown.",
        },
        "S3": {
            "kind": "intake_status", "version": "v1",
            "body": "Engine logs for the previous ten days and PMS have NOT BEEN SUPPLIED. Last overhaul date is unknown.",
        },
    }
    candidate = {
        "schema": SCHEMA, "model_id": "qwen3:1.7b",
        "model_digest": "a" * 64, "prompt_version": "synthetic-v1",
        "items": [
            {"kind": "event_notice", "source_id": "S1", "source_version": "v1",
             "verbatim_excerpt": "Turbocharger damage reportedly occurred on 16 July 2025."},
            {"kind": "reported_statement", "source_id": "S2", "source_version": "v1",
             "verbatim_excerpt": "Chief Engineer reported abnormal vibration and high exhaust temperature before shutdown."},
            {"kind": "intake_status", "source_id": "S3", "source_version": "v1",
             "verbatim_excerpt": "Engine logs for the previous ten days and PMS have NOT BEEN SUPPLIED."},
        ],
    }
    return sources, candidate


class LocalAICandidateGate(unittest.TestCase):
    def test_grounded_synthetic_excerpts_are_pending_review_only(self):
        sources, candidate = synthetic_fixture()
        result = evaluate_synthetic_source_quotes(sources, candidate)
        self.assertEqual(result["quote_count"], 3)
        self.assertTrue(result["human_review_required"])
        self.assertFalse(result["authoritative_fact_updates"])
        self.assertFalse(result["coverage_or_liability_decisions"])
        self.assertFalse(result["pilot_accepted"])
        self.assertNotIn("Chief Engineer", str(result))
        self.assertNotIn("Owner notification", str(result))

    def reject(self, code, sources, candidate):
        with self.assertRaises(LocalAISourceGateError) as ex:
            evaluate_synthetic_source_quotes(sources, candidate)
        self.assertEqual(str(ex.exception), code)
        self.assertNotIn("Turbocharger", str(ex.exception))

    def test_invented_witness_claim_or_unsourced_causation_is_refused(self):
        sources, candidate = synthetic_fixture()
        for invented in (
            "Chief Engineer says bearing failure caused the loss.",
            "The damage was unrelated to planned maintenance.",
            "The insurer should presume negligence because engine logs were absent.",
            "The policy covers this loss and the reserve is approved.",
        ):
            changed = deepcopy(candidate)
            changed["items"][1]["verbatim_excerpt"] = invented
            with self.subTest(invented=invented):
                self.reject("unsupported_quote", sources, changed)

    def test_cannot_change_report_into_established_event(self):
        sources, candidate = synthetic_fixture()
        changed = deepcopy(candidate)
        changed["items"][1]["kind"] = "event_notice"
        self.reject("source_lineage_mismatch", sources, changed)

    def test_missing_submitted_records_cannot_be_relabelled(self):
        sources, candidate = synthetic_fixture()
        changed = deepcopy(candidate)
        changed["items"][2]["kind"] = "reported_statement"
        self.reject("source_lineage_mismatch", sources, changed)
        changed = deepcopy(candidate)
        changed["items"][2]["verbatim_excerpt"] = "The engine logs never existed."
        self.reject("unsupported_quote", sources, changed)

    def test_no_model_generated_coverage_liability_or_free_text_channel(self):
        sources, candidate = synthetic_fixture()
        for field in ("coverage", "liability", "narrative", "allegations", "thinking"):
            changed = deepcopy(candidate)
            changed[field] = "approved"
            with self.subTest(field=field):
                self.reject("invalid_candidate", sources, changed)
        changed = deepcopy(candidate)
        changed["items"][0]["interpretation"] = "Bearing failure proven"
        self.reject("invalid_item_shape", sources, changed)

    def test_unknown_source_version_or_duplicate_quote_is_refused(self):
        sources, candidate = synthetic_fixture()
        changed = deepcopy(candidate)
        changed["items"][0]["source_id"] = "S4"
        self.reject("unknown_source", sources, changed)
        changed = deepcopy(candidate)
        changed["items"][0]["source_version"] = "v2"
        self.reject("source_lineage_mismatch", sources, changed)
        changed = deepcopy(candidate)
        changed["items"].append(deepcopy(changed["items"][0]))
        self.reject("duplicate_quote", sources, changed)

    def test_bad_model_metadata_cannot_claim_identity(self):
        sources, candidate = synthetic_fixture()
        changed = deepcopy(candidate)
        changed["model_digest"] = "not-a-digest"
        self.reject("invalid_model_metadata", sources, changed)
        changed = deepcopy(candidate)
        changed["schema"] = "unreviewed-v0"
        self.reject("invalid_schema", sources, changed)
        changed = deepcopy(candidate)
        changed["model_id"] = "evil model key"
        self.reject("invalid_model_metadata", sources, changed)

    def test_malformed_untrusted_containers_fail_closed(self):
        sources, candidate = synthetic_fixture()
        self.reject("invalid_sources", [], candidate)
        self.reject("invalid_candidate", sources, [])
        changed = deepcopy(sources)
        changed["S2"]["kind"] = ["reported_statement"]
        self.reject("invalid_sources", changed, candidate)
        changed = deepcopy(candidate)
        changed["items"][1]["verbatim_excerpt"] = {"text": "not a string"}
        self.reject("unsupported_quote", sources, changed)
        changed = deepcopy(candidate)
        changed["items"] = []
        self.reject("invalid_items", sources, changed)
        changed = deepcopy(candidate)
        changed["items"] = changed["items"] * 100
        self.reject("invalid_items", sources, changed)


if __name__ == "__main__":
    unittest.main()

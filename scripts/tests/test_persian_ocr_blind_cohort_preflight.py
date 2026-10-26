"""Synthetic blind-cohort split and study-coverage regressions; no real data."""
import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.persian_ocr_blind_cohort_preflight import check_blind_cohort, main
from scripts.tests.test_persian_ocr_local_validation_metrics import example_study


def example_manifest():
    return {
        "schema_version": 1,
        "protocol_ref": "FICTION-PREREGISTERED-DRAFT-NOT-APPROVED",
        "minimum_blind_holdout_sources": 3,
        "predeclared_critical_kinds": [
            "negation", "uncertainty", "time", "technical_term",
        ],
        "sources": [
            {
                "case_ref": "DEVELOPMENT-ONLY",
                "source_file_sha256": "9" * 64,
                "split": "development",
                "source_kind": "scanned_pdf",
                "script_mix": "mixed_persian_latin",
                "expected_critical_kinds": ["negation"],
            },
            {
                "case_ref": "FICTION-HM1",
                "source_file_sha256": "a" * 64,
                "split": "blind_holdout",
                "source_kind": "native_scan",
                "script_mix": "persian",
                "expected_critical_kinds": ["negation", "technical_term", "causation"],
            },
            {
                "case_ref": "FICTION-HM2",
                "source_file_sha256": "c" * 64,
                "split": "blind_holdout",
                "source_kind": "photograph",
                "script_mix": "persian",
                "expected_critical_kinds": ["time", "technical_term"],
            },
            {
                "case_ref": "FICTION-HM3",
                "source_file_sha256": "e" * 64,
                "split": "blind_holdout",
                "source_kind": "scanned_pdf",
                "script_mix": "mixed_persian_latin",
                "expected_critical_kinds": ["uncertainty"],
            },
        ],
    }


class BlindStudyPreflightTests(unittest.TestCase):
    def test_complete_structural_cohort_never_grants_pilot_or_expert_review(self):
        result = check_blind_cohort(example_manifest(), example_study())
        self.assertTrue(result["submitted_holdout_structure_complete"])
        self.assertEqual(result["development_sources_registered"], 1)
        self.assertEqual(result["blind_holdout_sources_registered"], 3)
        self.assertEqual(result["blind_holdout_sources_with_study_pages"], 3)
        self.assertEqual(result["blind_holdout_sources_without_study_pages"], 0)
        self.assertEqual(result["required_critical_kinds_not_observed"], [])
        self.assertEqual(result["literal_metric_pages_screened"], 3)
        for key in (
            "pilot_accepted", "acceptance_thresholds_approved",
            "blinding_independently_attested",
            "source_bytes_independently_verified",
            "reference_transcripts_independently_adjudicated",
            "negation_scope_semantics_verified",
            "human_bilingual_review_completed",
        ):
            self.assertFalse(result[key])

    def test_structural_shortfalls_are_explicit_never_silent_pass(self):
        manifest = example_manifest()
        manifest["sources"].append({
            "case_ref": "FICTION-MISSING-CASE",
            "source_file_sha256": "8" * 64,
            "split": "blind_holdout",
            "source_kind": "native_scan",
            "script_mix": "persian",
            "expected_critical_kinds": ["negation"],
        })
        result = check_blind_cohort(manifest, example_study())
        self.assertEqual(result["blind_holdout_sources_without_study_pages"], 1)
        self.assertFalse(result["submitted_holdout_structure_complete"])
        manifest["minimum_blind_holdout_sources"] = 12
        short = check_blind_cohort(manifest, example_study())
        self.assertFalse(short["minimum_holdout_count_met"])
        self.assertFalse(short["submitted_holdout_structure_complete"])
        manifest["predeclared_critical_kinds"].append("other_critical_phrase")
        kinds = check_blind_cohort(manifest, example_study())
        self.assertEqual(kinds["required_critical_kinds_not_observed"], ["other_critical_phrase"])
        self.assertFalse(kinds["submitted_holdout_structure_complete"])

    def test_leakage_and_changed_source_lineage_fail_closed(self):
        cases = [
            lambda m, s: m["sources"][0].update({"case_ref": "FICTION-HM1"}),
            lambda m, s: m["sources"][0].update({"source_file_sha256": "a" * 64}),
            lambda m, s: m["sources"][1].update({"source_file_sha256": "9" * 64}),
            lambda m, s: s["records"][0].update({"source_file_sha256": "f" * 64}),
            lambda m, s: s["records"][0].update({"case_ref": "DEVELOPMENT-ONLY"}),
            lambda m, s: s["records"][0].update({"case_ref": "UNREGISTERED"}),
            lambda m, s: m["sources"][1].update({"split": "development"}),
            lambda m, s: m["sources"][1].update({"source_kind": "unsupported"}),
            lambda m, s: m["sources"][1].update({"script_mix": "unknown"}),
            lambda m, s: m["sources"][1].update({"expected_critical_kinds": ["time"]}),
            lambda m, s: m["sources"][1].update({"extra_approval": True}),
            lambda m, s: m.update({"blind_sources_verified": True}),
            lambda m, s: m.update({"minimum_blind_holdout_sources": True}),
            lambda m, s: m.update({"predeclared_critical_kinds": ["negation", "negation"]}),
        ]
        for i, mutation in enumerate(cases):
            manifest = copy.deepcopy(example_manifest())
            study = copy.deepcopy(example_study())
            mutation(manifest, study)
            with self.subTest(case=i), self.assertRaises(ValueError):
                check_blind_cohort(manifest, study)

    def test_cli_outputs_only_aggregate_and_rejects_duplicate_keys(self):
        manifest = example_manifest()
        study = example_study()
        with tempfile.TemporaryDirectory() as dir_name:
            m = Path(dir_name) / "private_manifest.json"
            s = Path(dir_name) / "private_measurements.json"
            m.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            s.write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                status = main(["--manifest", str(m), "--measurements", str(s)])
            self.assertEqual(status, 0)
            self.assertEqual(err.getvalue(), "")
            report = json.loads(out.getvalue())
            self.assertTrue(report["submitted_holdout_structure_complete"])
            for protected in ("FICTION-HM1", "DEVELOPMENT-ONLY", "توربوشارژر", "نیست", str(m), str(s)):
                self.assertNotIn(protected, out.getvalue())
            m.write_text(m.read_text(encoding="utf-8").replace(
                '"schema_version": 1,',
                '"schema_version": 1, "schema_version": 1,',
                1,
            ), encoding="utf-8")
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                status = main(["--manifest", str(m), "--measurements", str(s)])
            self.assertEqual(status, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue().strip(), "blind_cohort_input_rejected")


if __name__ == "__main__":
    unittest.main()

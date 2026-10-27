"""Fictional-only tests; no synthetic test impersonates independent reviewers."""
import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.persian_ocr_review_disagreement_metrics import (
    main, summarize_review_observations,
)
from scripts.tests.test_persian_ocr_blind_cohort_preflight import example_manifest
from scripts.tests.test_persian_ocr_local_validation_metrics import example_study


def fake_reviews():
    return {
        "schema_version": 1,
        "protocol_ref": "FICTION-PREREGISTERED-DRAFT-NOT-APPROVED",
        "rows": [
            {
                "case_ref": "FICTION-HM1",
                "page_locator": "page:1",
                "span_ref": "critical-negation",
                "source_file_sha256": "a" * 64,
                "extraction_sha256": "b" * 64,
                "reviewer_one": {
                    "reviewer_ref": "PSEUDO-A", "finding": "material_meaning_changed",
                },
                "reviewer_two": {
                    "reviewer_ref": "PSEUDO-B", "finding": "meaning_preserved",
                },
                "specialist_adjudication": None,
            },
            {
                "case_ref": "FICTION-HM1",
                "page_locator": "page:1",
                "span_ref": "machinery",
                "source_file_sha256": "a" * 64,
                "extraction_sha256": "b" * 64,
                "reviewer_one": {"reviewer_ref": "PSEUDO-A", "finding": "meaning_preserved"},
                "reviewer_two": {"reviewer_ref": "PSEUDO-B", "finding": "meaning_preserved"},
                "specialist_adjudication": None,
            },
            {
                "case_ref": "FICTION-HM2",
                "page_locator": "page:1",
                "span_ref": "time",
                "source_file_sha256": "c" * 64,
                "extraction_sha256": "d" * 64,
                "reviewer_one": {
                    "reviewer_ref": "PSEUDO-A", "finding": "material_meaning_changed",
                },
                "reviewer_two": {
                    "reviewer_ref": "PSEUDO-B", "finding": "material_meaning_changed",
                },
                "specialist_adjudication": {
                    "specialist_ref": "PSEUDO-C", "finding": "material_meaning_changed",
                },
            },
        ],
    }


class LocalReviewDisagreementMetricsTests(unittest.TestCase):
    def test_reports_agreement_disagreement_missing_and_specialist_triage(self):
        result = summarize_review_observations(
            manifest=example_manifest(), measurements=example_study(), reviews=fake_reviews(),
        )
        self.assertEqual(result["planned_critical_reference_positive_spans"], 4)
        overall = result["overall"]
        self.assertEqual(overall["reference_positive_spans"], 4)
        self.assertEqual(overall["two_assessment_rows_supplied"], 3)
        self.assertEqual(overall["reference_spans_with_no_review_row"], 1)
        self.assertEqual(overall["reviewers_agreed"], 2)
        self.assertEqual(overall["reviewers_disagreed"], 1)
        self.assertEqual(overall["reported_pairwise_agreement_rate"], 0.6667)
        self.assertEqual(overall["any_reviewer_reported_material_change"], 2)
        self.assertEqual(overall["specialist_adjudication_required"], 2)
        self.assertEqual(overall["specialist_adjudication_record_supplied"], 1)
        self.assertEqual(overall["specialist_adjudication_record_missing"], 1)
        self.assertEqual(result["by_kind"]["negation"]["reviewers_disagreed"], 1)
        self.assertEqual(result["by_kind"]["uncertainty"]["reference_spans_with_no_review_row"], 1)
        self.assertEqual(result["by_kind"]["time"]["adjudicator_reported_material_change"], 1)
        for field in (
            "reviewer_identity_independently_verified",
            "two_reviewers_actually_compared_scans_verified",
            "adjudicator_identity_or_authority_verified",
            "verbatim_reference_adjudicated",
            "negation_scope_accuracy_verified",
            "human_bilingual_review_completed",
            "critical_fact_authorization_granted",
            "pilot_accepted",
        ):
            self.assertIs(result[field], False)

    def test_zero_rows_is_missing_review_not_consensus_or_approval(self):
        reviews = fake_reviews()
        reviews["rows"] = []
        result = summarize_review_observations(
            manifest=example_manifest(), measurements=example_study(), reviews=reviews,
        )
        self.assertEqual(result["overall"]["reference_spans_with_no_review_row"], 4)
        self.assertIsNone(result["overall"]["reported_pairwise_agreement_rate"])
        self.assertFalse(result["pilot_accepted"])

    def test_fabricated_mismatched_or_duplicate_observations_rejected(self):
        changes = [
            lambda r: r.update({"schema_version": True}),
            lambda r: r.update({"protocol_ref": "DIFFERENT"}),
            lambda r: r.update({"reviewed_by_expert": True}),
            lambda r: r["rows"][0].update({"case_ref": "DEVELOPMENT-ONLY"}),
            lambda r: r["rows"][0].update({"span_ref": "negative-control"}),
            lambda r: r["rows"][0].update({"source_file_sha256": "f" * 64}),
            lambda r: r["rows"][0].update({"extraction_sha256": "f" * 64}),
            lambda r: r["rows"][0].update({"human_approved": True}),
            lambda r: r["rows"][0]["reviewer_two"].update({"reviewer_ref": "PSEUDO-A"}),
            lambda r: r["rows"][0]["reviewer_one"].update({"finding": "unknown"}),
            lambda r: r["rows"][0]["reviewer_one"].update({"source_quote": "SECRET"}),
            lambda r: r["rows"][0].update({"specialist_adjudication": {
                "specialist_ref": "PSEUDO-A", "finding": "material_meaning_changed",
            }}),
            lambda r: r["rows"][1].update({"specialist_adjudication": {
                "specialist_ref": "PSEUDO-C", "finding": "meaning_preserved",
            }}),
            lambda r: r["rows"].append(copy.deepcopy(r["rows"][0])),
        ]
        for n, change in enumerate(changes):
            reviews = copy.deepcopy(fake_reviews())
            change(reviews)
            with self.subTest(change=n), self.assertRaises(ValueError):
                summarize_review_observations(
                    manifest=example_manifest(), measurements=example_study(), reviews=reviews,
                )

    def test_cli_generic_errors_and_aggregate_output_never_expose_private_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / "manifest.json"
            measurement = root / "measurements.json"
            reviews = root / "reviews.json"
            for path, data in (
                (manifest, example_manifest()),
                (measurement, example_study()),
                (reviews, fake_reviews()),
            ):
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            cmd = [
                "--manifest", str(manifest),
                "--measurements", str(measurement),
                "--reviews", str(reviews),
            ]
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(cmd)
            self.assertEqual(code, 0)
            self.assertEqual(err.getvalue(), "")
            report = json.loads(out.getvalue())
            self.assertEqual(report["overall"]["reviewers_disagreed"], 1)
            for private in ("PSEUDO-A", "FICTION-HM1", "توربوشارژر", "نیست", str(root)):
                self.assertNotIn(private, out.getvalue() + err.getvalue())
            reviews.write_text(reviews.read_text(encoding="utf-8").replace(
                '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1,
            ), encoding="utf-8")
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(cmd)
            self.assertEqual(code, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue().strip(), "ocr_review_observations_rejected")


if __name__ == "__main__":
    unittest.main()

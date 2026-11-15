"""Synthetic-only safety and denominator tests for private-local OCR metrics."""
import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.persian_ocr_local_validation_metrics import (
    evaluate_local_study, main,
)


def example_study():
    """All text and identifiers here are fictional/public test material."""
    return {
        "schema_version": 1,
        "records": [
            {
                "case_ref": "FICTION-HM1",
                "page_locator": "page:1",
                "document_version": 1,
                "source_file_sha256": "a" * 64,
                "extraction_sha256": "b" * 64,
                "reference_page_text": (
                    "توربوشارژر؛ علت قطعی خرابی هنوز معلوم نیست "
                    "و بررسی سوابق ضروری است."
                ),
                "ocr_page_text": "توربوشارژر انفجار",
                "ocr_page_complete": True,
                "critical_spans": [
                    {
                        "span_ref": "critical-negation", "kind": "negation",
                        "literal": "علت قطعی خرابی هنوز معلوم نیست",
                        "expected_present": True, "search_exact_hit": False,
                    },
                    {
                        "span_ref": "machinery", "kind": "technical_term",
                        "literal": "توربوشارژر",
                        "expected_present": True, "search_exact_hit": False,
                    },
                    {
                        "span_ref": "negative-control", "kind": "causation",
                        "literal": "انفجار",
                        "expected_present": False, "search_exact_hit": None,
                    },
                ],
            },
            {
                "case_ref": "FICTION-HM2",
                "page_locator": "page:1",
                "document_version": 2,
                "source_file_sha256": "c" * 64,
                "extraction_sha256": "d" * 64,
                "reference_page_text": "شاید در ساعت ۱۰:۰۰ نشت رخ داده است.",
                "ocr_page_text": "شاید در ساعت ۱۰:۰۰ نشت رخ داده است.",
                "ocr_page_complete": True,
                "critical_spans": [
                    {
                        "span_ref": "time", "kind": "time",
                        "literal": "ساعت ۱۰:۰۰",
                        "expected_present": True, "search_exact_hit": True,
                    },
                    {
                        "span_ref": "negative-control", "kind": "technical_term",
                        "literal": "سوختگی",
                        "expected_present": False, "search_exact_hit": None,
                    },
                ],
            },
            {
                "case_ref": "FICTION-HM3",
                "page_locator": "page:1",
                "document_version": 1,
                "source_file_sha256": "e" * 64,
                "extraction_sha256": "f" * 64,
                "reference_page_text": "علت هنوز معلوم نیست.",
                "ocr_page_text": "",
                "ocr_page_complete": False,
                "critical_spans": [
                    {
                        "span_ref": "uncertain", "kind": "uncertainty",
                        "literal": "معلوم نیست",
                        "expected_present": True, "search_exact_hit": None,
                    },
                ],
            },
        ],
    }


class LocalPersianOcrValidationTests(unittest.TestCase):
    def test_separates_ocr_omission_retrieval_gap_insertion_and_unknown(self):
        actual = evaluate_local_study(example_study())
        self.assertEqual(actual["pages_measured_or_screened"], 3)
        total = actual["overall"]
        self.assertEqual(total["reference_positive"], 4)
        self.assertEqual(total["ocr_positive_measured"], 3)
        self.assertEqual(total["ocr_exact_found"], 2)
        self.assertEqual(total["ocr_exact_missing"], 1)
        self.assertEqual(total["ocr_positive_unknown"], 1)
        self.assertEqual(total["reference_negative_controls"], 2)
        self.assertEqual(total["ocr_false_insertion"], 1)
        self.assertEqual(total["ocr_negative_measured"], 2)
        self.assertEqual(total["search_measured_given_ocr_found"], 2)
        self.assertEqual(total["search_exact_found"], 1)
        self.assertEqual(total["search_exact_missing"], 1)
        self.assertEqual(total["ocr_exact_literal_recall_measured_only"], 0.6667)
        self.assertEqual(total["reference_positive_observation_coverage"], 0.75)
        self.assertEqual(total["ocr_exact_literal_recall_all_reference_lower_bound"], 0.5)
        self.assertEqual(total["ocr_exact_literal_recall_all_reference_upper_bound"], 0.75)
        self.assertEqual(
            actual["by_kind"]["uncertainty"]["reference_positive_observation_coverage"], 0.0
        )
        self.assertEqual(
            actual["by_kind"]["uncertainty"]["ocr_exact_literal_recall_all_reference_lower_bound"], 0.0
        )
        self.assertEqual(
            actual["by_kind"]["uncertainty"]["ocr_exact_literal_recall_all_reference_upper_bound"], 1.0
        )
        self.assertEqual(total["false_insertion_rate_on_negative_controls"], 0.5)
        self.assertEqual(total["search_exact_retrieval_given_ocr_literal_present"], 0.5)
        self.assertLess(total["ocr_exact_literal_recall_wilson95_descriptive"]["lower"], 0.6667)
        self.assertGreater(total["ocr_exact_literal_recall_wilson95_descriptive"]["upper"], 0.6667)
        self.assertEqual(actual["by_kind"]["negation"]["ocr_exact_missing"], 1)
        self.assertEqual(actual["by_kind"]["technical_term"]["search_exact_missing"], 1)
        self.assertEqual(actual["by_kind"]["uncertainty"]["ocr_positive_unknown"], 1)
        self.assertFalse(actual["pilot_accepted"])
        self.assertFalse(actual["human_bilingual_review_completed"])
        self.assertFalse(actual["reference_transcript_independently_adjudicated"])
        self.assertFalse(actual["negation_scope_semantics_verified"])

    def test_same_page_literal_cannot_be_counted_twice_under_new_label_or_kind(self):
        # New IDs or category changes do not create independent observations.
        for replacement_kind in ("technical_term", "negation", "uncertainty"):
            study = example_study()
            duplicate = copy.deepcopy(study["records"][0]["critical_spans"][1])
            duplicate["span_ref"] = "inflated-second-observation"
            duplicate["kind"] = replacement_kind
            study["records"][0]["critical_spans"].append(duplicate)
            with self.subTest(kind=replacement_kind):
                with self.assertRaisesRegex(
                    ValueError, "^invalid_or_incomplete_local_study_input$"
                ):
                    evaluate_local_study(study)

    def test_repeat_literal_on_different_independent_page_is_not_rejected(self):
        study = example_study()
        another_page = copy.deepcopy(study["records"][0])
        another_page["case_ref"] = "FICTION-HM4"
        another_page["source_file_sha256"] = "0" * 64
        another_page["extraction_sha256"] = "1" * 64
        study["records"].append(another_page)
        result = evaluate_local_study(study)
        self.assertEqual(result["pages_measured_or_screened"], 4)
        self.assertEqual(result["overall"]["reference_positive"], 6)
        self.assertEqual(result["overall"]["ocr_positive_measured"], 5)
        self.assertEqual(result["overall"]["ocr_exact_found"], 3)
        self.assertFalse(result["pilot_accepted"])

    def test_same_source_page_under_different_case_alias_is_not_independent(self):
        study = example_study()
        # Keep identical original bytes and page, but disguise the source with
        # a new case ID, document version, and extraction digest.
        alias = copy.deepcopy(study["records"][0])
        alias["case_ref"] = "FICTION-ALIAS-OF-HM1"
        alias["document_version"] = 42
        alias["extraction_sha256"] = "9" * 64
        study["records"].append(alias)
        with self.assertRaisesRegex(
            ValueError, "^invalid_or_incomplete_local_study_input$"
        ):
            evaluate_local_study(study)

    def test_same_document_distinct_page_locator_is_separate_claimed_page(self):
        study = example_study()
        next_page = copy.deepcopy(study["records"][0])
        next_page["page_locator"] = "page:2"
        next_page["extraction_sha256"] = "9" * 64
        study["records"].append(next_page)
        report = evaluate_local_study(study)
        self.assertEqual(report["pages_measured_or_screened"], 4)
        self.assertEqual(report["overall"]["reference_positive"], 6)
        self.assertEqual(report["source_and_extraction_hashes"], "format_checked_not_source_attested")
        self.assertFalse(report["reference_transcript_independently_adjudicated"])
        self.assertFalse(report["pilot_accepted"])

    def test_alias_source_cli_fails_without_printing_paths_hashes_or_text(self):
        study = example_study()
        alias = copy.deepcopy(study["records"][0])
        alias["case_ref"] = "PRIVATE-FAKE-ALIAS"
        alias["extraction_sha256"] = "9" * 64
        study["records"].append(alias)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private_study_input.json"
            path.write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(["--input", str(path)])
            self.assertEqual(exit_code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue().strip(), "ocr_validation_input_rejected")
            self.assertNotIn("PRIVATE-FAKE-ALIAS", stderr.getvalue())
            self.assertNotIn("توربوشارژر", stderr.getvalue())
            self.assertNotIn("a" * 64, stderr.getvalue())
            self.assertNotIn(str(path), stderr.getvalue())

    def test_duplicate_span_cli_rejects_without_echoing_local_text(self):
        study = example_study()
        duplicate = copy.deepcopy(study["records"][0]["critical_spans"][0])
        duplicate["span_ref"] = "other-fictitious-label"
        study["records"][0]["critical_spans"].append(duplicate)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private_local_input.json"
            path.write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["--input", str(path)])
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue().strip(), "ocr_validation_input_rejected")
            self.assertNotIn("معلوم نیست", stderr.getvalue())
            self.assertNotIn(str(path), stderr.getvalue())

    def test_no_denominator_is_not_perfect_score(self):
        study = example_study()
        study["records"] = study["records"][2:]
        result = evaluate_local_study(study)
        self.assertIsNone(result["overall"]["ocr_exact_literal_recall_measured_only"])
        self.assertIsNone(result["overall"]["ocr_exact_literal_recall_wilson95_descriptive"])
        self.assertEqual(result["overall"]["reference_positive_observation_coverage"], 0.0)
        self.assertEqual(result["overall"]["ocr_exact_literal_recall_all_reference_lower_bound"], 0.0)
        self.assertEqual(result["overall"]["ocr_exact_literal_recall_all_reference_upper_bound"], 1.0)
        self.assertIsNone(result["overall"]["false_insertion_rate_on_negative_controls"])
        self.assertIsNone(result["overall"]["search_exact_retrieval_given_ocr_literal_present"])
        self.assertEqual(result["overall"]["ocr_positive_unknown"], 1)

    def test_measured_only_perfect_score_does_not_hide_unknown_positive_pages(self):
        study = example_study()
        # Complete and found on one page, unknown on another: raw measured
        # recall is 100%, but 50% of reference-positive observations are unmeasured.
        complete = copy.deepcopy(study["records"][0])
        complete["critical_spans"] = [complete["critical_spans"][1]]
        complete["ocr_page_text"] = "توربوشارژر"
        missing = copy.deepcopy(study["records"][2])
        missing["critical_spans"] = [missing["critical_spans"][0]]
        study["records"] = [complete, missing]
        report = evaluate_local_study(study)["overall"]
        self.assertEqual(report["reference_positive"], 2)
        self.assertEqual(report["ocr_exact_literal_recall_measured_only"], 1.0)
        self.assertEqual(report["reference_positive_observation_coverage"], 0.5)
        self.assertEqual(report["ocr_exact_literal_recall_all_reference_lower_bound"], 0.5)
        self.assertEqual(report["ocr_exact_literal_recall_all_reference_upper_bound"], 1.0)

    def test_incomplete_negative_controls_cannot_look_like_zero_insertion(self):
        study = example_study()
        unknown_control = copy.deepcopy(study["records"][1])
        unknown_control["case_ref"] = "FICTION-HM4"
        unknown_control["source_file_sha256"] = "0" * 64
        unknown_control["extraction_sha256"] = "1" * 64
        unknown_control["ocr_page_complete"] = False
        unknown_control["ocr_page_text"] = ""
        unknown_control["critical_spans"] = [unknown_control["critical_spans"][1]]
        study["records"].append(unknown_control)

        report = evaluate_local_study(study)
        total = report["overall"]
        self.assertEqual(total["reference_negative_controls"], 3)
        self.assertEqual(total["ocr_negative_measured"], 2)
        self.assertEqual(total["ocr_negative_unknown"], 1)
        self.assertEqual(total["ocr_false_insertion"], 1)
        self.assertEqual(total["false_insertion_rate_on_negative_controls"], 0.5)
        self.assertEqual(total["reference_negative_observation_coverage"], 0.6667)
        self.assertEqual(total["false_insertion_rate_all_negative_lower_bound"], 0.3333)
        self.assertEqual(total["false_insertion_rate_all_negative_upper_bound"], 0.6667)
        self.assertEqual(
            report["by_kind"]["technical_term"]["reference_negative_observation_coverage"], 0.5
        )
        self.assertEqual(
            report["by_kind"]["technical_term"]["false_insertion_rate_all_negative_lower_bound"], 0.0
        )
        self.assertEqual(
            report["by_kind"]["technical_term"]["false_insertion_rate_all_negative_upper_bound"], 0.5
        )
        self.assertFalse(report["pilot_accepted"])
        self.assertFalse(report["negation_scope_semantics_verified"])

        # No complete OCR on any reference-negative control does not mean
        # a measured 0% false-insertion rate; all such controls stay unknown.
        study["records"] = [unknown_control]
        unknown_only = evaluate_local_study(study)["overall"]
        self.assertIsNone(unknown_only["false_insertion_rate_on_negative_controls"])
        self.assertEqual(unknown_only["reference_negative_observation_coverage"], 0.0)
        self.assertEqual(unknown_only["false_insertion_rate_all_negative_lower_bound"], 0.0)
        self.assertEqual(unknown_only["false_insertion_rate_all_negative_upper_bound"], 1.0)

    def test_zero_negative_controls_have_null_coverage_and_bounds(self):
        study = example_study()
        for page in study["records"]:
            page["critical_spans"] = [
                span for span in page["critical_spans"] if span["expected_present"]
            ]
        report = evaluate_local_study(study)["overall"]
        self.assertEqual(report["reference_negative_controls"], 0)
        self.assertIsNone(report["false_insertion_rate_on_negative_controls"])
        self.assertIsNone(report["reference_negative_observation_coverage"])
        self.assertIsNone(report["false_insertion_rate_all_negative_lower_bound"])
        self.assertIsNone(report["false_insertion_rate_all_negative_upper_bound"])

    def test_zero_reference_positive_has_no_claimed_recall_bounds(self):
        study = example_study()
        page = study["records"][0]
        page["critical_spans"] = [page["critical_spans"][2]]
        result = evaluate_local_study({"schema_version": 1, "records": [page]})
        overall = result["overall"]
        self.assertEqual(overall["reference_positive"], 0)
        self.assertIsNone(overall["ocr_exact_literal_recall_measured_only"])
        self.assertIsNone(overall["reference_positive_observation_coverage"])
        self.assertIsNone(overall["ocr_exact_literal_recall_all_reference_lower_bound"])
        self.assertIsNone(overall["ocr_exact_literal_recall_all_reference_upper_bound"])
        self.assertFalse(result["pilot_accepted"])

    def test_bad_or_contradictory_provenance_input_fails_closed(self):
        originals = example_study()
        changes = [
            lambda p: p.update({"schema_version": True}),
            lambda p: p.update({"unexpected_approval": True}),
            lambda p: p["records"][0].update({"source_file_sha256": "not a digest"}),
            lambda p: p["records"][0].update({"ocr_page_complete": 1}),
            lambda p: p["records"][0].update({"document_version": False}),
            lambda p: p["records"][0]["critical_spans"][0].update({"kind": "pilot_passed"}),
            lambda p: p["records"][0]["critical_spans"][0].update({"expected_present": False}),
            lambda p: p["records"][0]["critical_spans"][0].update({"search_exact_hit": True}),
            lambda p: p["records"][0]["critical_spans"][2].update({"search_exact_hit": True}),
            lambda p: p["records"][0]["critical_spans"][0].update({"approved": True}),
            lambda p: p["records"].append(copy.deepcopy(p["records"][0])),
            lambda p: p["records"][0]["critical_spans"].append(
                copy.deepcopy(p["records"][0]["critical_spans"][0])
            ),
        ]
        for change in changes:
            bad = copy.deepcopy(originals)
            change(bad)
            with self.subTest(change=changes.index(change)):
                with self.assertRaises(ValueError):
                    evaluate_local_study(bad)

    def test_cli_never_prints_private_spans_quotes_or_source_identifiers(self):
        study = example_study()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private_study_input.json"
            path.write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = main(["--input", str(path)])
            self.assertEqual(status, 0)
            self.assertEqual(stderr.getvalue(), "")
            response = json.loads(stdout.getvalue())
            self.assertEqual(response["overall"]["ocr_exact_missing"], 1)
            self.assertNotIn("FICTION-HM1", stdout.getvalue())
            self.assertNotIn("توربوشارژر", stdout.getvalue())
            self.assertNotIn("نیست", stdout.getvalue())
            self.assertNotIn(str(path), stdout.getvalue())

            study["records"][0]["source_file_sha256"] = "bad"
            path.write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = main(["--input", str(path)])
            self.assertEqual(status, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue().strip(), "ocr_validation_input_rejected")


    def test_duplicate_keys_fail_without_echoing_private_input(self):
        study = example_study()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sensitive.json"
            encoded = json.dumps(study, ensure_ascii=False)
            # The second key could otherwise silently override the first.
            encoded = encoded.replace(
                '"schema_version": 1,',
                '"schema_version": 1, "schema_version": 1,',
                1,
            )
            path.write_text(encoded, encoding="utf-8")
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["--input", str(path)])
            self.assertEqual(result, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue().strip(), "ocr_validation_input_rejected")


if __name__ == "__main__":
    unittest.main()

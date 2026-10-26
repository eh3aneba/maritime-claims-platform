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

    def test_no_denominator_is_not_perfect_score(self):
        study = example_study()
        study["records"] = study["records"][2:]
        result = evaluate_local_study(study)
        self.assertIsNone(result["overall"]["ocr_exact_literal_recall_measured_only"])
        self.assertIsNone(result["overall"]["ocr_exact_literal_recall_wilson95_descriptive"])
        self.assertIsNone(result["overall"]["false_insertion_rate_on_negative_controls"])
        self.assertIsNone(result["overall"]["search_exact_retrieval_given_ocr_literal_present"])
        self.assertEqual(result["overall"]["ocr_positive_unknown"], 1)

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

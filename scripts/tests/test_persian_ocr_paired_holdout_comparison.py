"""Fictional matched-source OCR A/B observations; cannot certify semantic safety."""
import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.persian_ocr_paired_holdout_comparison import (
    compare_paired_ocr_studies, main,
)
from scripts.tests.test_persian_ocr_offline_study_run import bundled_study


def candidate_study(baseline: dict) -> dict:
    new = copy.deepcopy(baseline)
    first = new["records"][0]
    # Invented candidate restores the missing negative clause, removes a
    # hallucinated machinery event; this is not actual engine performance.
    first["ocr_page_text"] = "توربوشارژر؛ علت قطعی خرابی هنوز معلوم نیست"
    first["extraction_sha256"] = "1" * 64
    first["critical_spans"][0]["search_exact_hit"] = None
    second = new["records"][1]
    # Explicit safety regression: candidate loses the incident clock.
    second["ocr_page_text"] = "شاید نشت رخ داده است."
    second["extraction_sha256"] = "2" * 64
    second["critical_spans"][0]["search_exact_hit"] = None
    return new


class PairedOcrHoldoutComparisonTests(unittest.TestCase):
    def test_recovered_negation_is_not_automatic_win_when_time_regresses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest, inventory, baseline = bundled_study(root)
            candidate = candidate_study(baseline)
            report = compare_paired_ocr_studies(
                manifest=manifest, inventory=inventory,
                baseline=baseline, candidate=candidate, root=root,
            )
            overall = report["comparison"]["overall"]
            self.assertEqual(report["pages_matched"], 3)
            self.assertEqual(overall["reference_positive_spans"], 4)
            self.assertEqual(overall["candidate_recovered_baseline_missing"], 1)
            self.assertEqual(overall["candidate_lost_baseline_present"], 1)
            self.assertEqual(overall["both_literal_present"], 1)
            self.assertEqual(overall["baseline_or_candidate_unmeasured"], 1)
            self.assertEqual(overall["candidate_removed_false_insertion"], 1)
            self.assertEqual(
                report["comparison"]["by_kind"]["negation"]["candidate_recovered_baseline_missing"], 1
            )
            self.assertEqual(
                report["comparison"]["by_kind"]["time"]["candidate_lost_baseline_present"], 1
            )
            self.assertTrue(report["same_declared_sources_and_reference_spans"])
            for key in (
                "file_origin_independently_attested",
                "blinding_independently_attested",
                "reference_transcripts_independently_adjudicated",
                "human_bilingual_review_completed",
                "negation_scope_semantics_verified",
                "candidate_automatically_selected",
                "production_ocr_changed",
                "critical_fact_authorization_granted",
                "pilot_accepted",
            ):
                self.assertIs(report[key], False)
            safe = json.dumps(report, ensure_ascii=False)
            for marker in ("FICTION-HM1", "توربوشارژر", "نیست", "scan-0.bin", str(root)):
                self.assertNotIn(marker, safe)

    def test_any_different_source_reference_span_or_page_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest, inventory, baseline = bundled_study(root)
            changes = [
                lambda c: c["records"][0].update({"document_version": 2}),
                lambda c: c["records"][0].update({"reference_page_text":
                    c["records"][0]["reference_page_text"] + " افزودنی"}),
                lambda c: c["records"][0]["critical_spans"][0].update({
                    "literal": "معلوم نیست"}),
                lambda c: c["records"][0]["critical_spans"][0].update({
                    "span_ref": "changed-id"}),
                lambda c: c["records"][0]["critical_spans"][1].update({
                    "kind": "causation"}),
                lambda c: c["records"][0].update({"extraction_sha256": "bad-digest"}),
                lambda c: c["records"].pop(),
                lambda c: c["records"][0].update({"source_file_sha256": "9" * 64}),
            ]
            for n, change in enumerate(changes):
                candidate = candidate_study(baseline)
                change(candidate)
                with self.subTest(case=n), self.assertRaises(ValueError):
                    compare_paired_ocr_studies(
                        manifest=manifest, inventory=inventory,
                        baseline=baseline, candidate=candidate, root=root,
                    )

    def test_unknown_incomplete_candidate_is_not_reported_as_a_literal_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest, inventory, baseline = bundled_study(root)
            candidate = candidate_study(baseline)
            candidate["records"][1]["ocr_page_text"] = ""
            candidate["records"][1]["ocr_page_complete"] = False
            report = compare_paired_ocr_studies(
                manifest=manifest, inventory=inventory,
                baseline=baseline, candidate=candidate, root=root,
            )
            self.assertEqual(
                report["comparison"]["by_kind"]["time"]["candidate_lost_baseline_present"], 0
            )
            self.assertEqual(
                report["comparison"]["by_kind"]["time"]["baseline_or_candidate_unmeasured"], 1
            )
            self.assertFalse(report["pilot_accepted"])

    def test_cli_never_outputs_private_material_or_partial_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest, inventory, baseline = bundled_study(root)
            candidate = candidate_study(baseline)
            names = [
                "private_manifest.json", "private_inventory.json",
                "private_baseline.json", "private_candidate.json",
            ]
            paths = [root / name for name in names]
            for path, obj in zip(paths, (manifest, inventory, baseline, candidate)):
                path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            args = [
                "--manifest", str(paths[0]),
                "--inventory", str(paths[1]),
                "--baseline", str(paths[2]),
                "--candidate", str(paths[3]),
                "--source-root", str(root),
            ]
            output, error = StringIO(), StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                code = main(args)
            self.assertEqual(code, 0)
            self.assertEqual(error.getvalue(), "")
            obj = json.loads(output.getvalue())
            self.assertFalse(obj["candidate_automatically_selected"])
            self.assertEqual(
                obj["comparison"]["by_kind"]["time"]["candidate_lost_baseline_present"], 1
            )
            for marker in ("FICTION-HM1", "نیست", "توربوشارژر", "scan-0.bin", str(root)):
                self.assertNotIn(marker, output.getvalue() + error.getvalue())
            # A tampered candidate/source observation must print nothing.
            paths[3].write_text(
                paths[3].read_text(encoding="utf-8").replace(
                    '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1
                ), encoding="utf-8",
            )
            output, error = StringIO(), StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                code = main(args)
            self.assertEqual(code, 2)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(error.getvalue().strip(), "paired_persian_ocr_study_rejected")


if __name__ == "__main__":
    unittest.main()

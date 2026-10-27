"""Synthetic-only preprocessing experiment: failure and privacy contract tests."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.hm_persian_ocr_probe import PROBES, SCOPED_NEGATION_PHRASE
from scripts.persian_ocr_synthetic_preprocessing_comparison import (
    PSM_MODES, VARIANTS, compare_synthetic_preprocessing, main,
)
from scripts.persian_ocr_tesseract_psm_ablation import PNG_SIGNATURE


def example_images():
    original = PNG_SIGNATURE + b"FICTIONAL-RASTER"
    reference = {
        "schema_version": 1,
        "source_file_sha256": hashlib.sha256(original).hexdigest(),
        "probes": [
            {"kind": "machinery_term", "literal": PROBES[0]},
            {"kind": "negation_token", "literal": PROBES[1]},
            {"kind": "negation_clause", "literal": SCOPED_NEGATION_PHRASE},
            {"kind": "incident_date", "literal": "۲۰۲۶-۰۹-۱۱"},
        ],
    }
    images = {
        "original": original,
        "grayscale_2x": PNG_SIGNATURE + b"FICTION-GRAY2",
        "grayscale_threshold_2x": PNG_SIGNATURE + b"FICTION-THRESHOLD2",
    }
    return images, reference


class SyntheticPreprocessingSafetyTests(unittest.TestCase):
    def test_all_settings_same_reference_and_date_regression_visible(self):
        images, reference = example_images()
        called = []
        def fake_ocr(command, **kwargs):
            self.assertEqual(command[0], "tesseract")
            self.assertEqual(command[2:6], ["stdout", "-l", "eng+fas", "--psm"])
            self.assertEqual(kwargs["capture_output"], True)
            self.assertGreater(kwargs["timeout"], 0)
            variant = Path(command[1]).stem
            self.assertEqual(Path(command[1]).read_bytes(), images[variant])
            psm = int(command[-1])
            called.append((variant, psm))
            if variant == "original":
                txt = PROBES[0] + " ۲۰۲۶-۰۹-۱۱"
            elif variant == "grayscale_2x":
                txt = PROBES[0] + " " + SCOPED_NEGATION_PHRASE.rstrip(".")
            else:
                txt = PROBES[0] + " " + SCOPED_NEGATION_PHRASE + " ۲۰۲۶-۰۹-۱۱"
            return subprocess.CompletedProcess(command, 0, stdout=txt, stderr="")
        report = compare_synthetic_preprocessing(images, reference, runner=fake_ocr)
        self.assertEqual(called, [(v, p) for v in VARIANTS for p in PSM_MODES])
        self.assertEqual(len(report["observations"]), 6)
        a = report["observations"]
        self.assertFalse(a[0]["negation_token_exact_present"])
        self.assertTrue(a[0]["incident_date_exact_present"])
        self.assertTrue(a[2]["negative_clause_core_present"])
        self.assertTrue(a[2]["date_missing_or_changed"])
        self.assertFalse(a[2]["all_critical_literals_present"])
        self.assertTrue(a[4]["all_critical_literals_present"])
        self.assertFalse(report["production_ocr_changed"])
        self.assertFalse(report["winning_variant_selected"])
        self.assertFalse(report["negation_scope_semantics_verified"])
        self.assertFalse(report["human_expert_review_completed"])
        self.assertFalse(report["pilot_accepted"])
        self.assertEqual(report["independent_unseen_scans_evaluated"], 0)
        shown = json.dumps(report, ensure_ascii=False)
        for forbidden in (PROBES[0], PROBES[1], SCOPED_NEGATION_PHRASE, "۲۰۲۶-۰۹-۱۱", "FICTION-RASTER"):
            self.assertNotIn(forbidden, shown)

    def test_missing_variant_hash_drift_failed_engine_or_timeout_rejected(self):
        images, reference = example_images()
        missing = dict(images)
        missing.pop("grayscale_threshold_2x")
        with self.assertRaises(ValueError):
            compare_synthetic_preprocessing(missing, reference)
        changed = dict(reference)
        changed["source_file_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            compare_synthetic_preprocessing(images, changed)
        mutated = dict(images)
        mutated["grayscale_2x"] = b"not a PNG"
        with self.assertRaises(ValueError):
            compare_synthetic_preprocessing(mutated, reference)
        def invalid_engine(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="PRIVATE-TEXT")
        with self.assertRaises(ValueError):
            compare_synthetic_preprocessing(images, reference, runner=invalid_engine)
        def timedout(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="PRIVATE")
        with self.assertRaises(subprocess.TimeoutExpired):
            compare_synthetic_preprocessing(images, reference, runner=timedout)

    def test_cli_rejects_private_or_non_fixed_sources_and_redacts_errors(self):
        # CLI is intentionally restricted to the known invented source.
        output, errors = StringIO(), StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(output), redirect_stderr(errors):
            main(["--image", "/private/client.png"])
        self.assertNotIn("/private/client.png", output.getvalue() + errors.getvalue())
        with patch(
            "scripts.persian_ocr_synthetic_preprocessing_comparison.synthetic_hm05_image_and_reference",
            side_effect=RuntimeError("private OCR error"),
        ):
            output, errors = StringIO(), StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                status = main(["--fixed-synthetic-hm05"])
            self.assertEqual(status, 2)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(errors.getvalue().strip(), "synthetic_persian_preprocessing_probe_rejected")


if __name__ == "__main__":
    unittest.main()

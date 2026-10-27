"""Synthetic-only PSM experiment contract tests (mock OCR is NOT accuracy data)."""
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
from scripts.persian_ocr_tesseract_psm_ablation import (
    MODES,
    PNG_SIGNATURE,
    evaluate_psm_ablation,
    main,
    validate_probe_reference,
)


def invented_source():
    # Fake bytes are only used for protocol tests, never interpreted as pixels.
    image = PNG_SIGNATURE + b"FIXTURE-WITH-NO-PERSONAL-DATA"
    reference = {
        "schema_version": 1,
        "source_file_sha256": hashlib.sha256(image).hexdigest(),
        "probes": [
            {"kind": "machinery_term", "literal": PROBES[0]},
            {"kind": "negation_token", "literal": PROBES[1]},
            {"kind": "negation_clause", "literal": SCOPED_NEGATION_PHRASE},
        ],
    }
    return image, reference


class PersianOcrPsmAblationTests(unittest.TestCase):
    def test_baseline_vs_candidates_stay_descriptive_and_do_not_rewrite_source(self):
        image, reference = invented_source()
        modes_seen = []
        def fake_engine(command, **kwargs):
            self.assertEqual(command[:1], ["tesseract"])
            self.assertEqual(command[2:6], ["stdout", "-l", "eng+fas", "--psm"])
            self.assertTrue(Path(command[1]).read_bytes() == image)
            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["timeout"] > 0)
            mode = int(command[-1])
            modes_seen.append(mode)
            content = {
                3: PROBES[0],
                4: PROBES[0] + " " + PROBES[1],
                6: PROBES[0] + " " + SCOPED_NEGATION_PHRASE,
                11: "",
            }[mode]
            return subprocess.CompletedProcess(command, 0, stdout=content, stderr="")
        report = evaluate_psm_ablation(image=image, reference=reference, runner=fake_engine)
        self.assertEqual(tuple(modes_seen), MODES)
        self.assertEqual(report["baseline_default_psm"], 3)
        rows = report["observations"]
        self.assertEqual([x["number_of_exact_probes_present"] for x in rows], [1, 2, 3, 0])
        self.assertFalse(rows[0]["negation_token_exact_present"])
        self.assertFalse(rows[1]["full_negation_clause_exact_present"])
        self.assertTrue(rows[2]["full_negation_clause_exact_present"])
        self.assertFalse(report["production_settings_changed"])
        self.assertFalse(report["best_mode_selected"])
        self.assertFalse(report["negation_scope_semantics_verified"])
        self.assertFalse(report["pilot_accepted"])
        raw = json.dumps(report, ensure_ascii=False)
        for marker in (PROBES[0], PROBES[1], SCOPED_NEGATION_PHRASE, "FIXTURE"):
            self.assertNotIn(marker, raw)

    def test_malformed_source_probe_hash_or_reference_fail_closed(self):
        image, reference = invented_source()
        mutation_cases = [
            lambda r: r.update({"source_file_sha256": "a" * 64}),
            lambda r: r.update({"schema_version": True}),
            lambda r: r.update({"approved_by_hm_specialist": True}),
            lambda r: r["probes"][0].update({"kind": "negation_token"}),
            lambda r: r["probes"][0].update({"kind": "unknown"}),
            lambda r: r["probes"][0].update({"literal": ""}),
            lambda r: r["probes"][0].update({"literal": 123}),
            lambda r: r["probes"][0].update({"human_verified": True}),
            lambda r: r["probes"][2].update({"literal": "not a negative phrase"}),
        ]
        for n, mutate in enumerate(mutation_cases):
            clone = json.loads(json.dumps(reference, ensure_ascii=False))
            mutate(clone)
            with self.subTest(n=n), self.assertRaises(ValueError):
                validate_probe_reference(clone, image)
        with self.assertRaises(ValueError):
            validate_probe_reference(reference, b"NOT A PNG")
        with self.assertRaises(ValueError):
            validate_probe_reference(reference, image + b"tampered")

    def test_engine_error_or_timeout_does_not_create_partial_quality_report(self):
        image, reference = invented_source()
        def failed_engine(command, **kwargs):
            if command[-1] == "3":
                return subprocess.CompletedProcess(command, 0, stdout=PROBES[0], stderr="")
            return subprocess.CompletedProcess(command, 1, stdout=PROBES[1], stderr="private image/path")
        with self.assertRaises(ValueError):
            evaluate_psm_ablation(image=image, reference=reference, runner=failed_engine)
        def timed_out(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="secret")
        with self.assertRaises(subprocess.TimeoutExpired):
            evaluate_psm_ablation(image=image, reference=reference, runner=timed_out)

    def test_cli_has_no_private_source_quotes_or_exception_details(self):
        image, reference = invented_source()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "private.png"
            ref_path = root / "private.json"
            path.write_bytes(image)
            ref_path.write_text(json.dumps(reference, ensure_ascii=False), encoding="utf-8")
            argv = ["--image", str(path), "--reference", str(ref_path)]
            with patch("scripts.persian_ocr_tesseract_psm_ablation.shutil.which", return_value="/usr/bin/tesseract"):
                # Patch the engine's full evaluation at the CLI boundary; not
                # an actual OCR experiment, only CLI output/error contract.
                with patch("scripts.persian_ocr_tesseract_psm_ablation.evaluate_psm_ablation") as mocked:
                    mocked.return_value = {
                        "measurement_kind": "mock_not_real_ocr",
                        "pilot_accepted": False,
                    }
                    out, err = StringIO(), StringIO()
                    with redirect_stdout(out), redirect_stderr(err):
                        result = main(argv)
                    self.assertEqual(result, 0)
                    self.assertEqual(err.getvalue(), "")
                    self.assertEqual(json.loads(out.getvalue())["pilot_accepted"], False)
                    for private in (str(root), PROBES[0], PROBES[1], "FIXTURE"):
                        self.assertNotIn(private, out.getvalue())
                    mocked.side_effect = RuntimeError("sensitive OCR error detail")
                    out, err = StringIO(), StringIO()
                    with redirect_stdout(out), redirect_stderr(err):
                        result = main(argv)
                    self.assertEqual(result, 2)
                    self.assertEqual(out.getvalue(), "")
                    self.assertEqual(err.getvalue().strip(), "persian_ocr_local_psm_ablation_rejected")
            ref_path.write_text(ref_path.read_text(encoding="utf-8").replace(
                '"schema_version": 1,',
                '"schema_version": 1, "schema_version": 1,',
                1,
            ), encoding="utf-8")
            with patch("scripts.persian_ocr_tesseract_psm_ablation.shutil.which", return_value="/usr/bin/tesseract"):
                out, err = StringIO(), StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    result = main(argv)
            self.assertEqual(result, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue().strip(), "persian_ocr_local_psm_ablation_rejected")


if __name__ == "__main__":
    unittest.main()

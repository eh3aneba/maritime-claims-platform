"""Fail closed if the *real OCR* GitHub job becomes a private-data pipeline."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
REAL_WORKFLOW = ROOT / ".github/workflows/persian-ocr-real-synthetic-probe.yml"


class SyntheticRealOcrWorkflowPolicyTests(unittest.TestCase):
    def test_real_runner_must_only_generate_fixed_public_hm05_in_memory(self):
        text = REAL_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: Real Synthetic Persian OCR Probe", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("pull_request:", text)
        self.assertIn("contents: read", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("AI_PROVIDER: disabled", text)
        self.assertIn('OPENAI_API_KEY: ""', text)
        self.assertIn("--fixed-synthetic-hm05", text)
        self.assertEqual(text.count("--fixed-synthetic-hm05"), 2)
        self.assertIn("python -m scripts.persian_ocr_synthetic_preprocessing_comparison", text)
        self.assertIn("synthetic-hm05-preprocessing-observations.json", text)
        self.assertIn("python -m scripts.persian_ocr_tesseract_psm_ablation", text)
        self.assertIn("tesseract-ocr-fas", text)
        self.assertIn("tests/browser/requirements.lock", text)
        self.assertIn("--require-hashes", text)
        self.assertIn("python -m playwright install --with-deps chromium", text)
        self.assertNotIn("--image ", text)
        self.assertNotIn("--reference ", text)
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("upload-artifact", text)
        self.assertNotIn("persist-credentials: true", text)
        self.assertNotIn("contents: write", text)

    def test_report_has_non_go_and_distinct_date_and_negation_checks(self):
        text = REAL_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('assert report["pilot_accepted"] is False', text)
        self.assertIn('assert report["best_mode_selected"] is False', text)
        self.assertIn('assert report["production_settings_changed"] is False', text)
        self.assertIn('assert report["negation_scope_semantics_verified"] is False', text)
        self.assertIn("incident_date_exact_present", text)
        self.assertIn("negation_token_exact_present", text)
        self.assertIn("negation_clause_core_without_terminal_punctuation_present", text)
        self.assertIn("Full clause", text)
        self.assertIn("Successful job status means experiment execution only.", text)
        self.assertIn("GITHUB_STEP_SUMMARY", text)
        self.assertIn("if: always()", text)
        self.assertIn("synthetic-hm05-psm-observations.json", text)


if __name__ == "__main__":
    unittest.main()

"""Synthetic HM-05 only: image preprocessing / Tesseract diagnostic matrix.

Never handles customer files or touches the production OCR extractor.
A found literal does not certify negation scope; a lost date is material.
Only aggregate booleans are emitted; the in-memory OCR transcript is not
logged, persisted, or exported, and no candidate is auto-promoted.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable

from scripts.persian_ocr_tesseract_psm_ablation import (
    MAX_IMAGE_BYTES, MAX_OCR_OUTPUT_CHARS, PNG_SIGNATURE, TIMEOUT_SECONDS,
    synthetic_hm05_image_and_reference, validate_probe_reference,
)

VARIANTS = ("original", "grayscale_2x", "grayscale_threshold_2x")
PSM_MODES = (3, 6)

# Browser Canvas changes pixels only; never edits any reference or recognized
# text. The input remains the exact fixed fictional Chromium screenshot.
_CANVAS_TRANSFORM = """
async ({ sourceBase64, variant }) => {
  const source = new Image();
  source.src = "data:image/png;base64," + sourceBase64;
  await source.decode();
  const canvas = document.createElement("canvas");
  canvas.width = source.naturalWidth * 2;
  canvas.height = source.naturalHeight * 2;
  const ctx = canvas.getContext("2d", {willReadFrequently: true});
  if (!ctx) throw new Error("canvas_unavailable");
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.filter = "grayscale(100%)";
  ctx.fillStyle = "white";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  if (variant === "grayscale_threshold_2x") {
    const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
    for (let index = 0; index < frame.data.length; index += 4) {
      const value = frame.data[index] < 180 ? 0 : 255;
      frame.data[index] = value;
      frame.data[index+1] = value;
      frame.data[index+2] = value;
      frame.data[index+3] = 255;
    }
    ctx.putImageData(frame, 0, 0);
  }
  return canvas.toDataURL("image/png").split(",")[1];
}
"""


def make_synthetic_variants(original: bytes) -> dict[str, bytes]:
    """Purely fictional pixels, with explicit optical transforms via Chromium."""
    from playwright.sync_api import sync_playwright

    if not original.startswith(PNG_SIGNATURE) or len(original) > MAX_IMAGE_BYTES:
        raise ValueError("invalid_synthetic_image")
    images = {"original": original}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            original_b64 = base64.b64encode(original).decode("ascii")
            for name in VARIANTS[1:]:
                transformed = page.evaluate(
                    _CANVAS_TRANSFORM, {"sourceBase64": original_b64, "variant": name}
                )
                if type(transformed) is not str:
                    raise ValueError("synthetic_transform_failed")
                result = base64.b64decode(transformed, validate=True)
                if not (result.startswith(PNG_SIGNATURE) and 0 < len(result) <= MAX_IMAGE_BYTES):
                    raise ValueError("synthetic_transform_failed")
                images[name] = result
        finally:
            browser.close()
    return images


def compare_synthetic_preprocessing(
    images: dict[str, bytes], reference: dict[str, Any],
    *, runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Evaluate fixed literal probes; no semantic/quality promotion."""
    if type(images) is not dict or set(images) != set(VARIANTS):
        raise ValueError("synthetic_variant_matrix_incomplete")
    probes = validate_probe_reference(reference, images["original"])
    for name, raw in images.items():
        if (
            type(raw) is not bytes or not raw.startswith(PNG_SIGNATURE)
            or len(raw) > MAX_IMAGE_BYTES or len(raw) <= len(PNG_SIGNATURE)
        ):
            raise ValueError("invalid_synthetic_variant")
    observations = []
    with tempfile.TemporaryDirectory(prefix="mcri-fictional-ocr-preprocess-") as directory:
        for variant in VARIANTS:
            filename = Path(directory) / (variant + ".png")
            filename.write_bytes(images[variant])
            for psm in PSM_MODES:
                completed = runner(
                    ["tesseract", str(filename), "stdout", "-l", "eng+fas", "--psm", str(psm)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=TIMEOUT_SECONDS,
                )
                if completed.returncode != 0 or type(completed.stdout) is not str:
                    raise ValueError("synthetic_ocr_engine_error")
                text = completed.stdout
                if len(text) > MAX_OCR_OUTPUT_CHARS:
                    raise ValueError("synthetic_ocr_output_too_large")
                machinery = probes["machinery_term"] in text
                negation = probes["negation_token"] in text
                clause = probes["negation_clause"] in text
                core = probes["negation_clause"].rstrip(" .،؛") in text
                date = probes["incident_date"] in text
                observations.append({
                    "variant": variant,
                    "psm": psm,
                    "machinery_term_exact_present": machinery,
                    "negation_token_exact_present": negation,
                    "negative_clause_core_present": core,
                    "negative_clause_punctuation_exact_present": clause,
                    "incident_date_exact_present": date,
                    "all_critical_literals_present": machinery and core and date,
                    "date_missing_or_changed": not date,
                })
    return {
        "schema_version": 1,
        "measurement_kind": "single_fixed_fictional_image_preprocessing_ablation",
        "source_file_sha256_compared_to_self_supplied_reference": True,
        "variants": list(VARIANTS),
        "psm_modes": list(PSM_MODES),
        "observations": observations,
        "independent_unseen_scans_evaluated": 0,
        "production_ocr_changed": False,
        "winning_variant_selected": False,
        "negation_scope_semantics_verified": False,
        "date_meaning_verified": False,
        "human_expert_review_completed": False,
        "pilot_accepted": False,
        "warning": (
            "One known fictional source across six configurations, not six scans. "
            "Critical dates and negative clauses require independent review. "
            "No production recommendation or pilot GO is authorized."
        ),
    }


class _RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse normally echoes unknown parameters including private paths.
        self.exit(2, "synthetic_persian_preprocessing_probe_rejected\\n")


def main(argv: list[str] | None = None) -> int:
    parser = _RedactingArgumentParser(description="Synthetic-only optical preprocessing diagnostic")
    parser.add_argument("--fixed-synthetic-hm05", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        if args.fixed_synthetic_hm05 is not True:
            raise ValueError("synthetic_flag_required")
        original, reference = synthetic_hm05_image_and_reference()
        variants = make_synthetic_variants(original)
        report = compare_synthetic_preprocessing(variants, reference)
    except Exception:
        # Do not forward Playwright/Tesseract error strings or OCR transcript.
        print("synthetic_persian_preprocessing_probe_rejected", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Local, opt-in Tesseract page-segmentation ablation; NEVER change claims OCR.

Runs multiple fixed --psm choices against identical original PNG bytes.
Returns only lexical probe presence, not raw OCR or a recommended model.
This is an engineering diagnostic, NOT source transcription or semantic QA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable

from scripts.hm_persian_ocr_probe import PROBES, SCOPED_NEGATION_PHRASE
from scripts.persian_ocr_local_validation_metrics import _reject_duplicate_json_keys

MODES = (3, 4, 6, 11)
CATEGORIES = ("machinery_term", "negation_token", "negation_clause")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_REFERENCE_BYTES = 64 * 1024
MAX_OCR_OUTPUT_CHARS = 2_000_000
TIMEOUT_SECONDS = 40


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("invalid_persian_ocr_ablation_input")


def validate_probe_reference(reference: Any, image: bytes) -> dict[str, str]:
    _require(type(image) is bytes and len(PNG_SIGNATURE) < len(image) <= MAX_IMAGE_BYTES)
    _require(image.startswith(PNG_SIGNATURE))
    _require(type(reference) is dict and set(reference) == {
        "schema_version", "source_file_sha256", "probes",
    })
    _require(type(reference["schema_version"]) is int and reference["schema_version"] == 1)
    digest = reference["source_file_sha256"]
    _require(type(digest) is str and digest == hashlib.sha256(image).hexdigest())
    probes = reference["probes"]
    _require(type(probes) is list and len(probes) == len(CATEGORIES))
    kinds: dict[str, str] = {}
    for item in probes:
        _require(type(item) is dict and set(item) == {"kind", "literal"})
        kind = item["kind"]
        literal = item["literal"]
        _require(type(kind) is str and kind in CATEGORIES and kind not in kinds)
        _require(type(literal) is str and 1 <= len(literal) <= 2000)
        kinds[kind] = literal
    _require(set(kinds) == set(CATEGORIES))
    # Do not let self-reported references accidentally invert the relationship.
    _require(kinds["negation_token"] in kinds["negation_clause"])
    return kinds


def evaluate_psm_ablation(
    *, image: bytes, reference: Any,
    runner: Callable[..., Any] = subprocess.run,
    executable: str = "tesseract",
) -> dict[str, Any]:
    probes = validate_probe_reference(reference, image)
    _require(type(executable) is str and executable and "\x00" not in executable)
    observations = []
    with tempfile.TemporaryDirectory(prefix="mcri-synthetic-ocr-ablation-") as folder:
        path = Path(folder) / "unchanged-source.png"
        path.write_bytes(image)
        for mode in MODES:
            result = runner(
                [executable, str(path), "stdout", "-l", "eng+fas", "--psm", str(mode)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=TIMEOUT_SECONDS,
            )
            _require(result.returncode == 0)
            ocr = result.stdout
            _require(type(ocr) is str and len(ocr) <= MAX_OCR_OUTPUT_CHARS)
            found = {kind: literal in ocr for kind, literal in probes.items()}
            observations.append({
                "psm": mode,
                "machinery_term_exact_present": found["machinery_term"],
                "negation_token_exact_present": found["negation_token"],
                "full_negation_clause_exact_present": found["negation_clause"],
                "number_of_exact_probes_present": sum(found.values()),
                "probes_tested": len(probes),
                "ocr_text_human_verified": False,
            })

    return {
        "schema_version": 1,
        "measurement_kind": "fixed_source_tesseract_psm_exact_literal_ablation",
        "source_bytes_compared_to_self_supplied_digest": True,
        "languages": "eng+fas",
        "baseline_default_psm": 3,
        "mode_count": len(MODES),
        "observations": observations,
        "production_settings_changed": False,
        "best_mode_selected": False,
        "reference_transcript_independently_adjudicated": False,
        "negation_scope_semantics_verified": False,
        "human_bilingual_review_completed": False,
        "pilot_accepted": False,
        "warning": (
            "Literal hits on an unchanged image do not prove semantic accuracy, "
            "safety, generalization, source authenticity, model improvement "
            "or reviewer approval. The production OCR configuration is unchanged."
        ),
    }


def synthetic_hm05_image_and_reference() -> tuple[bytes, dict[str, Any]]:
    """Generate public invented HM-05 pixels through the existing Chromium path."""
    from playwright.sync_api import sync_playwright
    from scripts.hm_multidoc_packs import load_corpus, make_upload_bytes

    case = load_corpus()["cases"][4]
    _require(case["case_id"] == "HM-05")
    scan = next(doc for doc in case["documents"] if doc["format"] == "png")
    source = "\n".join(scan["source_lines"])
    _require(all(x in source for x in (*PROBES, SCOPED_NEGATION_PHRASE)))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            image, mime = make_upload_bytes(scan, page)
        finally:
            browser.close()
    _require(mime == "image/png")
    return image, {
        "schema_version": 1,
        "source_file_sha256": hashlib.sha256(image).hexdigest(),
        "probes": [
            {"kind": "machinery_term", "literal": PROBES[0]},
            {"kind": "negation_token", "literal": PROBES[1]},
            {"kind": "negation_clause", "literal": SCOPED_NEGATION_PHRASE},
        ],
    }


def _read_private_image(path: Path) -> bytes:
    _require(not path.is_symlink() and path.is_file())
    _require(0 < path.stat().st_size <= MAX_IMAGE_BYTES)
    return path.read_bytes()


def _read_private_reference(path: Path) -> Any:
    _require(not path.is_symlink() and path.is_file())
    _require(0 < path.stat().st_size <= MAX_REFERENCE_BYTES)
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=_reject_duplicate_json_keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare fixed local Tesseract PSM modes; diagnostic, not approval"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixed-synthetic-hm05", action="store_true")
    source.add_argument("--image", type=Path)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args(argv)
    try:
        _require(shutil.which("tesseract") is not None)
        if args.fixed_synthetic_hm05:
            _require(args.reference is None)
            image, reference = synthetic_hm05_image_and_reference()
        else:
            _require(args.reference is not None)
            image = _read_private_image(args.image)
            reference = _read_private_reference(args.reference)
        report = evaluate_psm_ablation(image=image, reference=reference)
    except Exception:
        # Strict privacy boundary: do not leak paths, output, source lines,
        # Tesseract stderr, Playwright exception strings or saved evidence.
        print("persian_ocr_local_psm_ablation_rejected", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

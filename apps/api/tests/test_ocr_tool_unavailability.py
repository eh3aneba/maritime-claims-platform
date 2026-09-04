from __future__ import annotations

from pathlib import Path

from app.modules.processing import extractors
from app.modules.processing.extractors import TextExtractionResult, TextSegmentResult


def test_selective_pdf_ocr_unavailable_preserves_native_text_and_requires_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    native = TextExtractionResult(
        method="pypdf",
        segments=[
            TextSegmentResult(
                locator_type="page",
                locator_value="1",
                text="Native machinery report text remains available for review.",
            ),
            TextSegmentResult(locator_type="page", locator_value="2", text=""),
        ],
        requires_ocr=True,
        warnings=["PDF contains 1 low-text page(s) that may require OCR."],
    )
    monkeypatch.setattr(extractors, "_tesseract_available", lambda: False)

    result = extractors._extract_pdf_ocr(
        tmp_path / "ocr-unavailable.pdf",
        native_result=native,
        languages="eng+fas",
        max_pages=20,
        timeout_seconds=5,
    )

    assert result.method == "pypdf+ocr_unavailable"
    assert result.requires_ocr is True
    assert result.segments == native.segments
    assert result.segments[0].locator_value == "1"
    assert result.segments[0].text == native.segments[0].text
    assert result.segments[1].locator_value == "2"
    assert result.segments[1].text == ""
    assert any("requires both Tesseract and pdftoppm" in warning for warning in result.warnings)

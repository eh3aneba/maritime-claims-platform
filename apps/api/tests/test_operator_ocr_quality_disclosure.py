"""Operator OCR status is not a claim of transcript accuracy.

The computed field deliberately does not inspect source text for negatives
and cannot turn a successful worker run into a human-approved document.
"""
import pytest

from app.modules.processing.schemas import DocumentProcessingSummary, TextExtractionSummary


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("tesseract:eng+fas", "ocr_human_source_comparison_required"),
        ("tesseract:fas", "ocr_human_source_comparison_required"),
        ("pypdf+selective-tesseract:eng+fas", "ocr_human_source_comparison_required"),
        ("pypdf+ocr_unavailable", "not_an_ocr_extraction"),
        ("pypdf", "not_an_ocr_extraction"),
        ("python-docx", "not_an_ocr_extraction"),
    ],
)
def test_operator_extraction_quality_disclaimer_is_derived_from_real_method(method, expected):
    extraction = TextExtractionSummary(
        extraction_method=method,
        extractor_version="1",
        char_count=123,
        segment_count=1,
        requires_ocr=False,
        text_hash="f" * 64,
        warnings=[],
    )
    # The disclosure must be present in the JSON response, not just a
    # transient Python property the operator UI cannot access.
    assert extraction.model_dump(mode="json")["source_text_quality_state"] == expected
    response = DocumentProcessingSummary(
        job=None,
        text_extraction=extraction,
        operator_status="completed",
        can_retry=False,
        retry_recommended=False,
        processing_release_required=False,
        processing_release_status="not_applicable",
    )
    data = response.model_dump(mode="json")
    assert data["text_extraction"]["source_text_quality_state"] == expected
    assert data["operator_status"] == "completed"
    assert data["text_extraction"]["requires_ocr"] is False
    # Processing being complete does NOT supply a human-verification
    # status or proof of negation/date/technical-term fidelity.
    assert not any(
        "verified" in key or "approved" in key
        for key in data["text_extraction"].keys()
    )

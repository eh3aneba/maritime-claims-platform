"""Operator OCR status is not a claim of transcript accuracy.

The computed field deliberately does not inspect source text for negatives
and cannot turn a successful worker run into a human-approved document.
"""
import pytest

from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from app.modules.processing.router import _pdf_input_signature_state, processing_summary
from app.modules.processing.schemas import DocumentProcessingSummary, TextExtractionSummary
from app.modules.documents.models import DocumentProcessingStatus


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
        pdf_signature_check_state=(
            "not_checked" if method.startswith("pypdf") else "not_declared_pdf"
        ),
        operator_status="completed",
        can_retry=False,
        retry_recommended=False,
        processing_release_required=False,
        processing_release_status="not_applicable",
    )
    data = response.model_dump(mode="json")
    assert data["text_extraction"]["source_text_quality_state"] == expected
    assert data["text_extraction"]["pdf_signature_check_state"] == (
        "not_checked" if method.startswith("pypdf") else "not_a_pdf_extraction"
    )
    assert data["operator_status"] == "completed"
    assert data["pdf_signature_check_state"] == (
        "not_checked" if method.startswith("pypdf") else "not_declared_pdf"
    )
    assert data["text_extraction"]["requires_ocr"] is False
    # Processing being complete does NOT supply a human-verification
    # status or proof of negation/date/technical-term fidelity.
    assert not any(
        "verified" in key or "approved" in key
        for key in data["text_extraction"].keys()
    )


@pytest.mark.parametrize(
    "method",
    [
        "pypdf",
        "pypdf+selective-tesseract:eng+fas",
        "pypdf+ocr_unavailable",
        "pypdf+selective-tesseract:fas",
    ],
)
def test_pdf_extraction_never_infers_cryptographic_signature_validity(method):
    extraction = TextExtractionSummary(
        extraction_method=method,
        extractor_version="2.1",
        char_count=125,
        segment_count=1,
        requires_ocr=False,
        text_hash="f" * 64,
        warnings=[],
    )
    # This value must never depend on OCR quality, returned text, page count,
    # file hash, or whether the alleged PDF signature is genuine or tampered.
    result = extraction.model_dump(mode="json")
    assert result["pdf_signature_check_state"] == "not_checked"
    assert result["text_hash"] == "f" * 64
    assert not any(
        key in result
        for key in ("signature_valid", "cryptographically_verified", "signer_verified")
    )


@pytest.mark.parametrize("method", ["python-docx", "openpyxl", "tesseract:eng+fas"])
def test_non_pdf_extractions_do_not_imply_pdf_signature_check(method):
    extraction = TextExtractionSummary(
        extraction_method=method,
        extractor_version="2.1",
        char_count=100,
        segment_count=1,
        requires_ocr=False,
        text_hash="a" * 64,
        warnings=[],
    )
    assert extraction.model_dump(mode="json")["pdf_signature_check_state"] == (
        "not_a_pdf_extraction"
    )


def test_real_synthetic_pdf_extraction_does_not_claim_signature_authenticity(tmp_path):
    """Real parser, synthetic blank PDF; not a cryptographic signed-PDF test."""
    from io import BytesIO
    from pypdf import PdfWriter

    from app.modules.processing.extractors import extract_document_text

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    stream = BytesIO()
    writer.write(stream)
    pdf_path = tmp_path / "synthetic-evidence.pdf"
    original = stream.getvalue()
    pdf_path.write_bytes(original)

    result = extract_document_text(pdf_path, enable_ocr=False)
    assert result.method == "pypdf"
    assert pdf_path.read_bytes() == original
    summary = TextExtractionSummary(
        extraction_method=result.method,
        extractor_version="2.1",
        char_count=len(result.combined_text),
        segment_count=len(result.segments),
        requires_ocr=result.requires_ocr,
        text_hash=result.text_hash,
        warnings=result.warnings,
    )
    data = summary.model_dump(mode="json")
    assert data["pdf_signature_check_state"] == "not_checked"
    assert data["text_hash"] is None
    # A successful parser and unchanged source bytes do not establish signer
    # authenticity; this smoke fixture deliberately contains no real signature.

@pytest.mark.parametrize(
    ("mime_type", "filename", "expected"),
    [
        ("application/pdf", "evidence.bin", "not_checked"),
        ("APPLICATION/PDF; charset=binary", "evidence.dat", "not_checked"),
        ("application/octet-stream", "SIGNED-REPORT.PDF", "not_checked"),
        ("image/png", "photo.png", "not_declared_pdf"),
        ("application/octet-stream", "report.pdf.exe", "not_declared_pdf"),
        (None, None, "not_declared_pdf"),
        ("image/png", "report.pdf", "not_checked"),
    ],
)
def test_pdf_input_disclosure_is_conservative_before_any_extraction(mime_type, filename, expected):
    assert _pdf_input_signature_state(
        mime_type=mime_type, original_filename=filename
    ) == expected


@pytest.mark.parametrize("state", [DocumentProcessingStatus.FAILED, DocumentProcessingStatus.UPLOADED])
def test_processing_response_exposes_pdf_not_checked_without_any_extraction(state):
    """An unsuccessful or absent OCR/PDF extraction cannot hide the PDF caution."""
    org_id, claim_id, doc_id = UUID(int=1), UUID(int=2), UUID(int=3)
    claim = SimpleNamespace(id=claim_id, organization_id=org_id)
    document = SimpleNamespace(
        id=doc_id, mime_type="application/octet-stream",
        original_filename="signed-evidence.pdf", processing_status=state,
    )
    current_user = SimpleNamespace(organization_id=org_id)
    with (
        patch(
            "app.modules.processing.router.get_claim_for_tenant",
            return_value=claim,
        ),
        patch(
            "app.modules.processing.router.get_document_for_tenant",
            return_value=document,
        ),
        patch(
            "app.modules.processing.router.get_processing_summary",
            return_value=(None, None),
        ),
        patch(
            "app.modules.processing.router.external_evidence_processing_release_status",
            return_value="not_applicable",
        ),
    ):
        result = processing_summary(
            claim_id=claim_id, document_id=doc_id, current_user=current_user,
            db=SimpleNamespace(),
        ).model_dump(mode="json")
    assert result["text_extraction"] is None
    assert result["pdf_signature_check_state"] == "not_checked"
    assert "signature_valid" not in result
    assert "signer_verified" not in result

def test_parser_detected_pdf_never_disappears_behind_mislabelled_input():
    assert _pdf_input_signature_state(
        mime_type="application/octet-stream",
        original_filename="evidence.bin",
        extraction_method="pypdf+selective-tesseract:eng+fas",
    ) == "not_checked"
    assert _pdf_input_signature_state(
        mime_type="application/octet-stream",
        original_filename="evidence.bin",
        extraction_method="python-docx",
    ) == "not_declared_pdf"

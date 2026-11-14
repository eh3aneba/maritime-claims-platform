"""Real synthetic self-signed PDF: extraction is not signature verification.

No customer documents, network, trust-store modification or production verifier.
An unchanged file hash means byte identity, not a trusted signer or valid signed
revision. OpenSSL checks here test the *fixture*, not an application capability.
"""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import shutil
import subprocess

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from pypdf import PdfReader

from app.modules.processing.extractors import extract_document_text
from app.modules.processing.schemas import TextExtractionSummary


def _synthetic_signed_pair() -> tuple[bytes, bytes, bytes, bytes, bytes]:
    """Create genuine detached-CMS PDF signature and change text *after* signing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    test_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "SeeClaims synthetic test only")
    ])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(test_name)
        .issuer_name(test_name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    # A fixed-length material textual change preserves xref offsets and PDF
    # readability but invalidates the original signed ByteRange.
    literal = b"Synthetic engine report: failure cause is not confirmed."
    page_stream = b"BT /F1 12 Tf 36 750 Td (" + literal + b") Tj ET"
    placeholder = b"<" + b"0" * 16384 + b">"
    placeholder_range = b"[0 0000000000 0000000000 0000000000]"
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [5 0 R] /SigFlags 3 >> >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
           b"<< /Font << /F1 4 0 R >> >> /Contents 7 0 R /Annots [5 0 R] >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        5: b"<< /Type /Annot /Subtype /Widget /FT /Sig /T (SyntheticSignature) "
           b"/Rect [0 0 0 0] /P 3 0 R /V 6 0 R >>",
        6: b"<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached "
           b"/ByteRange " + placeholder_range + b" /Contents " + placeholder + b" >>",
        7: b"<< /Length " + str(len(page_stream)).encode("ascii")
           + b" >>\nstream\n" + page_stream + b"\nendstream",
    }
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number, value in objects.items():
        offsets[number] = len(pdf)
        pdf += f"{number} 0 obj\n".encode("ascii") + value + b"\nendobj\n"
    xref_start = len(pdf)
    pdf += b"xref\n0 8\n0000000000 65535 f \n"
    for number in range(1, 8):
        pdf += f"{offsets[number]:010d} 00000 n \n".encode("ascii")
    pdf += (
        b"trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n"
        + str(xref_start).encode("ascii") + b"\n%%EOF\n"
    )
    original = bytes(pdf)
    start = original.index(b"/Contents " + placeholder) + len(b"/Contents ")
    end = start + len(placeholder)
    byte_range = (
        f"[0 {start:010d} {end:010d} {len(original) - end:010d}]"
    ).encode("ascii")
    assert len(byte_range) == len(placeholder_range)
    original = original.replace(placeholder_range, byte_range, 1)
    signed_content = original[:start] + original[end:]
    cms = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(signed_content)
        .add_signer(cert, private_key, hashes.SHA256())
        .sign(
            serialization.Encoding.DER,
            [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary],
        )
    )
    assert len(cms) * 2 <= 16384
    contents = b"<" + cms.hex().encode("ascii") + b"0" * (16384 - 2 * len(cms)) + b">"
    signed = original[:start] + contents + original[end:]
    tampered = signed.replace(b"not confirmed", b"now confirmed", 1)
    assert signed != tampered and len(signed) == len(tampered)
    return signed, tampered, cms, signed_content, tampered[:start] + tampered[end:]


@pytest.fixture(scope="module")
def signed_pdf_pair() -> tuple[bytes, bytes, bytes, bytes, bytes]:
    return _synthetic_signed_pair()


def test_both_intact_and_post_sign_modified_pdf_extract_without_signature_acceptance(
    tmp_path: Path, signed_pdf_pair: tuple[bytes, bytes, bytes, bytes, bytes],
) -> None:
    intact, tampered, _, _, _ = signed_pdf_pair
    assert sha256(intact).hexdigest() != sha256(tampered).hexdigest()
    for name, raw, expected_text in (
        ("intact", intact, "cause is not confirmed"),
        ("post-sign-modified", tampered, "cause is now confirmed"),
    ):
        source_path = tmp_path / f"{name}.pdf"
        source_path.write_bytes(raw)
        reader = PdfReader(BytesIO(raw))
        fields = reader.get_fields()
        assert fields and fields["SyntheticSignature"]["/FT"] == "/Sig"
        assert expected_text in reader.pages[0].extract_text()

        unchanged_sha = sha256(source_path.read_bytes()).hexdigest()
        extraction = extract_document_text(source_path, enable_ocr=False)
        assert extraction.method == "pypdf"
        assert expected_text in extraction.combined_text
        assert sha256(source_path.read_bytes()).hexdigest() == unchanged_sha
        summary = TextExtractionSummary(
            extraction_method=extraction.method,
            extractor_version="2.1",
            char_count=len(extraction.combined_text),
            segment_count=len(extraction.segments),
            requires_ocr=extraction.requires_ocr,
            text_hash=extraction.text_hash,
            warnings=extraction.warnings,
        ).model_dump(mode="json")
        assert summary["pdf_signature_check_state"] == "not_checked"
        assert "signature_valid" not in summary
        assert "signer_verified" not in summary
        assert "cryptographically_verified" not in summary


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI not installed")
def test_synthetic_cms_signature_verification_detects_post_sign_modification(
    tmp_path: Path, signed_pdf_pair: tuple[bytes, bytes, bytes, bytes, bytes],
) -> None:
    """Check the test fixture only, without creating a product verifier."""
    _, _, cms, valid_signed_range, modified_signed_range = signed_pdf_pair
    cms_path = tmp_path / "synthetic-detached.cms"
    cms_path.write_bytes(cms)
    results = []
    for label, signed_range in (
        ("intact", valid_signed_range),
        ("modified", modified_signed_range),
    ):
        payload = tmp_path / (label + ".data")
        payload.write_bytes(signed_range)
        # -noverify skips CA trust for this deliberately self-signed
        # *fixture*, but CMS signature/content integrity is still verified.
        completed = subprocess.run(
            [
                "openssl", "cms", "-verify", "-binary", "-inform", "DER",
                "-in", str(cms_path), "-content", str(payload),
                "-noverify", "-out", str(tmp_path / "verified.data"),
            ],
            capture_output=True, check=False, timeout=20,
        )
        results.append(completed.returncode)
    assert results[0] == 0
    assert results[1] != 0

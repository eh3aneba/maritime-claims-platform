"""Self-contained fictional signed PDF control; no production signature verification.

This test generates an ephemeral self-signed CMS-signature PDF and a same-length
tampered copy. OpenSSL verifies integrity of the intact covered byte ranges,
then rejects the changed page bytes. SeeClaims parsing must never claim the
signature or the signer is verified. Nothing sensitive is committed or logged.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from pypdf import PdfReader

from app.modules.processing.extractors import extract_document_text
from app.modules.processing.schemas import TextExtractionSummary


def _fictional_signed_pdf() -> tuple[bytes, bytes, tuple[int, int, int, int]]:
    """Generate a valid signature-field PDF; no actual trusted signing identity."""
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]

    def add_object(number: int, payload: bytes) -> None:
        assert number == len(offsets)
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(payload)
        pdf.extend(b"\nendobj\n")

    add_object(1, b"<< /Type /Catalog /Pages 2 0 R /AcroForm 5 0 R >>")
    add_object(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    add_object(
        3,
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> "
        b"/Contents 6 0 R /Annots [7 0 R] >>",
    )
    add_object(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    add_object(5, b"<< /SigFlags 3 /Fields [7 0 R] >>")
    drawing = b"BT /F1 12 Tf 72 720 Td (Engine stable) Tj ET"
    add_object(
        6,
        f"<< /Length {len(drawing)} >>\nstream\n".encode("ascii")
        + drawing + b"\nendstream",
    )
    add_object(
        7,
        b"<< /Type /Annot /Subtype /Widget /FT /Sig "
        b"/T (FictionalSignature) /Rect [0 0 0 0] /P 3 0 R /V 8 0 R >>",
    )
    capacity = 8192
    add_object(
        8,
        b"<< /Type /Sig /Filter /Adobe.PPKLite "
        b"/SubFilter /adbe.pkcs7.detached "
        b"/ByteRange [0000000000 0000000000 0000000000 0000000000] "
        b"/Contents <" + b"0" * (capacity * 2)
        + b"> /Name (FICTIONAL TEST CERT) >>",
    )

    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Root 1 0 R /Size {len(offsets)} >>\n"
        f"startxref\n{xref_start}\n%%EOF\n".encode("ascii")
    )

    contents_start = pdf.index(b"/Contents <") + len(b"/Contents ")
    contents_end = contents_start + 2 + capacity * 2
    byte_range = (0, contents_start, contents_end, len(pdf) - contents_end)
    placeholder = b"/ByteRange [0000000000 0000000000 0000000000 0000000000]"
    replacement = (
        b"/ByteRange [" + b" ".join(
            f"{number:010d}".encode("ascii") for number in byte_range
        ) + b"]"
    )
    assert len(placeholder) == len(replacement)
    position = pdf.index(placeholder)
    pdf[position:position + len(placeholder)] = replacement
    covered = bytes(pdf[:contents_start] + pdf[contents_end:])

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "FICTIONAL TEST CERT - UNTRUSTED")
    ])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(123456)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    cms = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(covered)
        .add_signer(certificate, private_key, hashes.SHA256())
        .sign(
            serialization.Encoding.DER,
            [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary],
        )
    )
    assert len(cms) < capacity
    pdf[contents_start + 1:contents_end - 1] = (
        cms.hex().encode("ascii")
        + b"0" * (capacity * 2 - len(cms.hex()))
    )
    return bytes(pdf), cms, byte_range


def _cryptographic_content_integrity(
    tmp_path: Path, *, pdf: bytes, cms: bytes, byte_range: tuple[int, int, int, int]
) -> bool:
    """Independent TEST-only integrity oracle: no chain/trust validation."""
    start, first_size, second_start, second_size = byte_range
    covered = pdf[start:start + first_size] + pdf[second_start:second_start + second_size]
    signature_path = tmp_path / "fictional.cms"
    content_path = tmp_path / "signed-ranges.bin"
    signature_path.write_bytes(cms)
    content_path.write_bytes(covered)
    completed = subprocess.run(
        [
            "openssl", "cms", "-verify", "-binary", "-inform", "DER",
            "-in", str(signature_path), "-content", str(content_path),
            "-noverify", "-out", os.devnull,
        ],
        capture_output=True,
        timeout=20,
        check=False,
    )
    return completed.returncode == 0


def test_intact_and_tampered_signed_pdf_both_remain_unverified_in_seeclaims(
    tmp_path: Path,
) -> None:
    # Missing test verifier is a failed acceptance control, never a green skip.
    assert shutil.which("openssl"), "OpenSSL CLI required for signed-PDF test"
    original, cms, byte_range = _fictional_signed_pdf()
    tampered = original.replace(b"Engine stable", b"Engine failed")
    assert original != tampered
    assert len(original) == len(tampered)
    assert _cryptographic_content_integrity(
        tmp_path, pdf=original, cms=cms, byte_range=byte_range
    ) is True
    assert _cryptographic_content_integrity(
        tmp_path, pdf=tampered, cms=cms, byte_range=byte_range
    ) is False

    for label, data, expected in (
        ("original", original, "Engine stable"),
        ("tampered", tampered, "Engine failed"),
    ):
        path = tmp_path / f"fictional-{label}.pdf"
        path.write_bytes(data)
        source_sha_before = sha256(path.read_bytes()).hexdigest()
        assert "FictionalSignature" in PdfReader(str(path)).get_fields()
        result = extract_document_text(path, enable_ocr=False)
        assert result.method == "pypdf"
        assert expected in result.combined_text
        assert path.read_bytes() == data
        assert sha256(path.read_bytes()).hexdigest() == source_sha_before
        summary = TextExtractionSummary(
            extraction_method=result.method,
            extractor_version="2.1",
            char_count=len(result.combined_text),
            segment_count=len(result.segments),
            requires_ocr=result.requires_ocr,
            text_hash=result.text_hash,
            warnings=result.warnings,
        ).model_dump(mode="json")
        assert summary["pdf_signature_check_state"] == "not_checked"
        assert summary["text_hash"] == result.text_hash
        for forbidden in ("signature_valid", "signer_verified", "cryptographically_verified"):
            assert forbidden not in summary

    assert sha256(original).digest() != sha256(tampered).digest()

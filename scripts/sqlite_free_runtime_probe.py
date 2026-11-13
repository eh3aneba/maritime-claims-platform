"""Offline, unprivileged synthetic PDF/OCR regression for the SQLite-free Worker.

Executed *inside* the final arm64 Worker image, with no network, no real
customer data, read-only rootfs and a disposable tmpfs for synthetic fixtures.
This does not test cryptographic PDF signature validation or authorize release.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from app.modules.processing.extractors import extract_document_text


def _run(args: list[str], *, timeout: int = 45) -> None:
    subprocess.run(args, check=True, timeout=timeout, capture_output=True)


def _no_sqlite_runtime() -> None:
    assert importlib.util.find_spec("_sqlite3") is None, "Python _sqlite3 was retained"
    assert shutil.which("sqlite3") is None, "SQLite CLI is present"
    assert subprocess.run(["/sbin/apk", "info", "-e", "sqlite-libs"], capture_output=True).returncode != 0
    for root in (Path("/usr/lib"), Path("/usr/local"), Path("/opt")):
        assert not any(
            p.is_file() and (p.name.startswith("libsqlite3.so") or p.name.startswith("_sqlite3."))
            for p in root.rglob("*")
        ), f"SQLite dynamic module/library is present under {root}"


def _pgm_pixels(path: Path) -> tuple[int, int, bytes]:
    payload = path.read_bytes()
    header = re.match(rb"P5\s+(\d+)\s+(\d+)\s+(\d+)\s", payload)
    assert header is not None, "Unexpected grayscale raster header"
    width, height, maximum = map(int, header.groups())
    pixels = payload[header.end():]
    assert 1000 <= width <= 2500 and 1000 <= height <= 3500 and maximum == 255
    assert len(pixels) == width * height and sum(p < 180 for p in pixels) > 3000
    return width, height, pixels


def main() -> None:
    _no_sqlite_runtime()
    assert shutil.which("pdftoppm") and shutil.which("tesseract")

    with tempfile.TemporaryDirectory(prefix="mcri-sqlite-free-") as directory:
        root = Path(directory)
        text_pdf = root / "native.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
        })
        native_stream = DecodedStreamObject()
        native_stream.set_data(
            b"BT /F1 20 Tf 55 650 Td (Synthetic marine claims evidence) Tj "
            b"0 -48 Td (nonroot worker processing) Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(native_stream)
        with text_pdf.open("xb") as stream:
            writer.write(stream)
        native = extract_document_text(text_pdf, enable_ocr=False)
        assert native.method == "pypdf" and not native.requires_ocr
        assert "Synthetic marine claims evidence" in native.combined_text

        # A real Poppler raster, re-embedded without any native PDF text.
        pgm_prefix = root / "text-raster"
        _run([
            "pdftoppm", "-f", "1", "-l", "1", "-singlefile",
            "-r", "200", "-gray", str(text_pdf), str(pgm_prefix),
        ])
        width, height, pixels = _pgm_pixels(pgm_prefix.with_suffix(".pgm"))
        scanned_pdf = root / "scanned.pdf"
        scanned_writer = PdfWriter()
        scanned_page = scanned_writer.add_blank_page(width=612, height=792)
        image = DecodedStreamObject()
        image.set_data(pixels)
        image = image.flate_encode()
        image.update(DictionaryObject({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(width),
            NameObject("/Height"): NumberObject(height),
            NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }))
        scanned_page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({
                NameObject("/Im1"): scanned_writer._add_object(image),
            }),
        })
        stream = DecodedStreamObject()
        stream.set_data(b"q 612 0 0 792 0 0 cm /Im1 Do Q")
        scanned_page[NameObject("/Contents")] = scanned_writer._add_object(stream)
        with scanned_pdf.open("xb") as output:
            scanned_writer.write(output)

        before = extract_document_text(scanned_pdf, enable_ocr=False)
        assert before.method == "pypdf" and before.requires_ocr
        assert not before.combined_text.strip(), "Fixture is not image-only"
        recovered = extract_document_text(
            scanned_pdf, enable_ocr=True,
            ocr_languages="eng+fas", ocr_max_pages=1, ocr_timeout_seconds=90,
        )
        assert recovered.method == "pypdf+selective-tesseract:eng+fas"
        assert not recovered.requires_ocr and recovered.text_hash is not None
        assert len(recovered.segments) == 1
        assert recovered.segments[0].locator_value == "1"
        assert "synthetic marine claims evidence" in recovered.combined_text.casefold(), (
            "Real eng+fas OCR did not recover the synthetic phrase"
        )
        print("PASS: no SQLite runtime, native PDF extraction and genuine offline eng+fas scanned-PDF OCR")
        print("NOT PROVEN: PDF signature verification, customer documents or deployment safety")


if __name__ == "__main__":
    main()

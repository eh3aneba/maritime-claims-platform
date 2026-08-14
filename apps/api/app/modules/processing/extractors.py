from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

EXTRACTOR_VERSION = "2.0"
MIN_MEANINGFUL_TEXT_CHARS = 40


@dataclass(frozen=True)
class TextSegmentResult:
    locator_type: str
    locator_value: str
    text: str


@dataclass(frozen=True)
class TextExtractionResult:
    method: str
    segments: list[TextSegmentResult] = field(default_factory=list)
    requires_ocr: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def combined_text(self) -> str:
        return "\n\n".join(segment.text for segment in self.segments if segment.text.strip())

    @property
    def text_hash(self) -> str | None:
        text = self.combined_text.strip()
        return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None


def extract_document_text(
    path: Path,
    *,
    enable_ocr: bool = False,
    ocr_languages: str = "eng+fas",
    ocr_max_pages: int = 20,
    ocr_timeout_seconds: float = 120.0,
) -> TextExtractionResult:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        result = _extract_pdf(path)
        if enable_ocr and result.requires_ocr:
            return _extract_pdf_ocr(
                path,
                languages=ocr_languages,
                max_pages=ocr_max_pages,
                timeout_seconds=ocr_timeout_seconds,
            )
        return result
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".xlsx":
        return _extract_xlsx(path)
    if suffix in {".jpg", ".jpeg", ".png"}:
        if enable_ocr:
            return _extract_image_ocr(
                path,
                languages=ocr_languages,
                timeout_seconds=ocr_timeout_seconds,
            )
        return TextExtractionResult(
            method="image_requires_ocr",
            requires_ocr=True,
            warnings=["Image documents require OCR; local OCR is not enabled for this process."],
        )
    raise ValueError(f"No text extractor is available for {suffix or 'this file type'}")


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_one_image(path: Path, *, languages: str, timeout_seconds: float) -> str:
    completed = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", languages],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return completed.stdout.strip()


def _extract_image_ocr(
    path: Path,
    *,
    languages: str,
    timeout_seconds: float,
) -> TextExtractionResult:
    if not _tesseract_available():
        return TextExtractionResult(
            method="tesseract_unavailable",
            requires_ocr=True,
            warnings=["Local OCR is enabled but the Tesseract binary is unavailable."],
        )
    try:
        text = _ocr_one_image(path, languages=languages, timeout_seconds=timeout_seconds)
    except (subprocess.SubprocessError, OSError) as exc:
        return TextExtractionResult(
            method="tesseract_failed",
            requires_ocr=True,
            warnings=[f"Local OCR failed: {type(exc).__name__}."],
        )
    return TextExtractionResult(
        method=f"tesseract:{languages}",
        segments=[TextSegmentResult(locator_type="page", locator_value="1", text=text)],
        requires_ocr=not bool(text.strip()),
        warnings=[] if text.strip() else ["OCR completed but produced no meaningful text."],
    )


def _extract_pdf_ocr(
    path: Path,
    *,
    languages: str,
    max_pages: int,
    timeout_seconds: float,
) -> TextExtractionResult:
    if not _tesseract_available() or shutil.which("pdftoppm") is None:
        return TextExtractionResult(
            method="tesseract_unavailable",
            requires_ocr=True,
            warnings=["Scanned PDF OCR requires both Tesseract and pdftoppm."],
        )
    max_pages = max(1, min(max_pages, 100))
    deadline = time.monotonic() + max(1.0, timeout_seconds)

    def remaining_seconds() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(cmd="pdf-ocr", timeout=timeout_seconds)
        return remaining

    try:
        with tempfile.TemporaryDirectory(prefix="mcri-ocr-") as directory:
            prefix = Path(directory) / "page"
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-l",
                    str(max_pages),
                    "-r",
                    "200",
                    "-png",
                    str(path),
                    str(prefix),
                ],
                check=True,
                capture_output=True,
                timeout=remaining_seconds(),
            )
            page_paths = sorted(Path(directory).glob("page-*.png"))
            segments = [
                TextSegmentResult(
                    locator_type="page",
                    locator_value=str(index),
                    text=_ocr_one_image(
                        page_path,
                        languages=languages,
                        timeout_seconds=remaining_seconds(),
                    ),
                )
                for index, page_path in enumerate(page_paths, start=1)
            ]
    except (subprocess.SubprocessError, OSError) as exc:
        return TextExtractionResult(
            method="tesseract_failed",
            requires_ocr=True,
            warnings=[f"Scanned PDF OCR failed: {type(exc).__name__}."],
        )
    has_text = any(segment.text.strip() for segment in segments)
    return TextExtractionResult(
        method=f"pdftoppm+tesseract:{languages}",
        segments=segments,
        requires_ocr=not has_text,
        warnings=([] if has_text else ["OCR completed but produced no meaningful text."]),
    )


def _extract_pdf(path: Path) -> TextExtractionResult:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    segments: list[TextSegmentResult] = []
    warnings: list[str] = []
    total_chars = 0
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        total_chars += len(text)
        segments.append(TextSegmentResult(locator_type="page", locator_value=str(index), text=text))
    requires_ocr = total_chars < MIN_MEANINGFUL_TEXT_CHARS
    if requires_ocr:
        warnings.append("PDF contains little or no extractable text and likely requires OCR.")
    return TextExtractionResult(
        method="pypdf", segments=segments, requires_ocr=requires_ocr, warnings=warnings
    )


def _extract_docx(path: Path) -> TextExtractionResult:
    from docx import Document as WordDocument

    document = WordDocument(str(path))
    blocks: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            blocks.append(text)
    for table_index, table in enumerate(document.tables, start=1):
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(" | ".join(cells))
        if rows:
            blocks.append(f"[Table {table_index}]\n" + "\n".join(rows))
    text = "\n\n".join(blocks)
    return TextExtractionResult(
        method="python-docx",
        segments=[TextSegmentResult(locator_type="document", locator_value="body", text=text)],
        requires_ocr=False,
    )


def _extract_xlsx(path: Path) -> TextExtractionResult:
    from openpyxl import load_workbook

    workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
    segments: list[TextSegmentResult] = []
    for worksheet in workbook.worksheets:
        lines: list[str] = []
        for row in worksheet.iter_rows(values_only=True):
            values = ["" if value is None else str(value) for value in row]
            if any(value for value in values):
                lines.append(" | ".join(values))
        segments.append(
            TextSegmentResult(
                locator_type="sheet", locator_value=worksheet.title[:100], text="\n".join(lines)
            )
        )
    workbook.close()
    return TextExtractionResult(method="openpyxl", segments=segments, requires_ocr=False)

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


EXTRACTOR_VERSION = "1.0"
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


def extract_document_text(path: Path) -> TextExtractionResult:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".xlsx":
        return _extract_xlsx(path)
    if suffix in {".jpg", ".jpeg", ".png"}:
        return TextExtractionResult(
            method="image_requires_ocr",
            requires_ocr=True,
            warnings=["Image documents require OCR; no OCR engine is enabled in Sprint 3 Phase A."],
        )
    raise ValueError(f"No text extractor is available for {suffix or 'this file type'}")


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
    return TextExtractionResult(method="pypdf", segments=segments, requires_ocr=requires_ocr, warnings=warnings)


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
            TextSegmentResult(locator_type="sheet", locator_value=worksheet.title[:100], text="\n".join(lines))
        )
    workbook.close()
    return TextExtractionResult(method="openpyxl", segments=segments, requires_ocr=False)

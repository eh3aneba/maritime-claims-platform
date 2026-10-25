"""Versioned invented H&M multi-document browser-test corpus, not production data.

Read-only corpus loader and in-memory DOCX/PNG renderers. No claims access,
network/AI calls, writes to storage, reviewer answers, or approval states.
The synthetic scan renderer requires an already active Playwright page.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import html
import json
from pathlib import Path
import re
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

CORPUS_PATH = Path(__file__).resolve().parents[1] / "docs/pilot/hm-multidoc-v1/cases.json"
_CASE_IDS = tuple(f"HM-{n:02d}" for n in range(1, 7))
_DOC_TYPES = frozenset({
    "claim_notification", "chief_engineer_report", "engine_log",
    "pms_record", "survey_report", "workshop_report", "quotation", "invoice",
})
_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
}


def load_corpus() -> dict[str, Any]:
    """Fail closed on fixture drift, missing version lineage or holdout leakage."""
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    if (
        type(corpus) is not dict
        or set(corpus) != {
            "corpus_id", "corpus_version", "fictional", "real_customer_data",
            "approved_expert_reference_included", "training_split_policy", "cases",
        }
        or corpus["corpus_id"] != "hm-machinery-six-multidoc-v1"
        or corpus["corpus_version"] != "1.0.0"
        or corpus["fictional"] is not True
        or corpus["real_customer_data"] is not False
        or corpus["approved_expert_reference_included"] is not False
        or type(corpus["cases"]) is not list
        or len(corpus["cases"]) != 6
        or [x.get("case_id") for x in corpus["cases"] if type(x) is dict] != list(_CASE_IDS)
        or [x.get("dataset_split") for x in corpus["cases"]] != [
            "development", "development", "development", "development", "holdout", "holdout",
        ]
    ):
        raise ValueError("invalid_synthetic_hm_corpus")
    for case in corpus["cases"]:
        if (
            type(case) is not dict
            or set(case) != {
                "case_id", "dataset_split", "scenario_focus",
                "incident_date", "notification_date", "claim_description",
                "currency", "documents",
            }
            or not 20 <= len(case["claim_description"]) <= 320
            or case["currency"] != "USD"
            or not re.fullmatch(r"2026-09-\d{2}", case["incident_date"])
            or not re.fullmatch(r"2026-09-\d{2}", case["notification_date"])
            or type(case["documents"]) is not list
            or not 4 <= len(case["documents"]) <= 6
        ):
            raise ValueError("invalid_synthetic_hm_case")
        seen: dict[str, dict[str, Any]] = {}
        for doc in case["documents"]:
            if (
                type(doc) is not dict
                or set(doc) != {
                    "source_id", "source_version", "file_name", "document_type",
                    "format", "replaces_source_id", "source_lines",
                }
                or type(doc["source_id"]) is not str
                or not re.fullmatch("[a-z][a-z0-9-]{1,24}", doc["source_id"])
                or doc["source_id"] in seen
                or type(doc["source_version"]) is not int
                or not 1 <= doc["source_version"] <= 2
                or type(doc["document_type"]) is not str
                or doc["document_type"] not in _DOC_TYPES
                or doc["format"] not in _MIME
                or doc["file_name"] != doc["source_id"] + "." + doc["format"]
                or type(doc["source_lines"]) is not list
                or not 3 <= len(doc["source_lines"]) <= 10
                or any(type(line) is not str or not 5 <= len(line) <= 260
                       for line in doc["source_lines"])
            ):
                raise ValueError("invalid_synthetic_hm_document")
            old = doc["replaces_source_id"]
            if old is not None:
                if (
                    type(old) is not str or old not in seen
                    or doc["source_version"] != seen[old]["source_version"] + 1
                    or doc["document_type"] != seen[old]["document_type"]
                    or doc["format"] != seen[old]["format"]
                ):
                    raise ValueError("invalid_synthetic_hm_replacement")
            elif doc["source_version"] != 1:
                raise ValueError("unlinked_synthetic_document_version")
            seen[doc["source_id"]] = doc
    if [d["format"] for c in corpus["cases"] for d in c["documents"]].count("png") != 1:
        raise ValueError("invalid_synthetic_hm_scan_count")
    return corpus


def make_docx_bytes(lines: list[str]) -> bytes:
    """Build uploadable OOXML from fixed invented source lines in memory."""
    body = "".join(
        '<w:p><w:r><w:t xml:space="preserve">' + escape(line) + '</w:t></w:r></w:p>'
        for line in lines
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>' + body + '<w:sectPr/></w:body></w:document>'
    )
    result = BytesIO()
    with ZipFile(result, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return result.getvalue()


def make_upload_bytes(document: dict[str, Any], page: Any | None = None) -> tuple[bytes, str]:
    """Render only validated in-repo invented documents; no general file input."""
    if document["format"] == "docx":
        return make_docx_bytes(document["source_lines"]), _MIME["docx"]
    if document["format"] != "png" or page is None:
        raise ValueError("synthetic_scan_browser_required")
    paragraphs = "".join("<p>" + html.escape(line) + "</p>"
                         for line in document["source_lines"])
    page.set_viewport_size({"width": 1500, "height": 900})
    page.set_content(
        '<main id="synthetic-scan" dir="rtl" '
        'style="box-sizing:border-box;width:1400px;height:800px;'
        'padding:55px 80px;background:white;color:black;'
        "font-family:'Noto Sans Arabic','Arial',sans-serif;"
        'font-size:48px;line-height:1.8;text-align:right;">'
        + paragraphs + '</main>'
    )
    payload = page.locator("#synthetic-scan").screenshot()
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("synthetic_scan_render_failed")
    return payload, _MIME["png"]


def observed_source_digest(case: dict[str, Any]) -> str:
    """Corpus drift reference only; not expert or model provenance attestation."""
    canonical = json.dumps(case["documents"], ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

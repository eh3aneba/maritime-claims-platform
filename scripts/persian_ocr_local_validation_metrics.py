"""Offline, descriptive page-scoped Persian OCR critical-span comparison.

Accept local manually prepared JSON only. Never send content to an API or
print source text, report identifiers, quotes or individual claim results.
No reviewer qualification, customer permission or semantic scope is verified.
Do not use these metrics to change pilot NO-GO.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

KINDS = (
    "negation",
    "uncertainty",
    "time",
    "causation",
    "technical_term",
    "other_critical_phrase",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_RECORDS = 2000
_MAX_SPANS_PER_PAGE = 100
_MAX_TEXT_CHARS = 200_000


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("invalid_or_incomplete_local_study_input")


def _keys(item: Any, fields: set[str]) -> None:
    _require(type(item) is dict and set(item) == fields)


def _text(value: Any, *, length: int = 100) -> str:
    _require(type(value) is str and 1 <= len(value) <= length)
    return value


def _hash(value: Any) -> str:
    s = _text(value, length=64)
    _require(_SHA256.fullmatch(s) is not None)
    return s


def _wilson(success: int, total: int) -> dict[str, float] | None:
    if total == 0:
        return None
    z = 1.959963984540054
    phat = success / total
    den = 1 + z * z / total
    mid = (phat + z * z / (2 * total)) / den
    rad = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / den
    return {"lower": round(max(0.0, mid - rad), 4), "upper": round(min(1.0, mid + rad), 4)}


def _blank() -> dict[str, int]:
    return {
        "reference_positive": 0,
        "reference_negative_controls": 0,
        "ocr_positive_measured": 0,
        "ocr_exact_found": 0,
        "ocr_exact_missing": 0,
        "ocr_positive_unknown": 0,
        "ocr_negative_measured": 0,
        "ocr_false_insertion": 0,
        "ocr_negative_unknown": 0,
        "search_measured_given_ocr_found": 0,
        "search_exact_found": 0,
        "search_exact_missing": 0,
        "search_unmeasured_given_ocr_found": 0,
    }


def evaluate_local_study(payload: Any) -> dict[str, Any]:
    """Deterministic literal observations; no inference about scope semantics."""
    _keys(payload, {"schema_version", "records"})
    _require(type(payload["schema_version"]) is int and payload["schema_version"] == 1)
    records = payload["records"]
    _require(type(records) is list and 1 <= len(records) <= _MAX_RECORDS)

    overall = _blank()
    by_kind = {kind: _blank() for kind in KINDS}
    seen_pages: set[tuple[str, str]] = set()
    for page in records:
        _keys(page, {
            "case_ref", "page_locator", "document_version", "source_file_sha256",
            "extraction_sha256", "reference_page_text", "ocr_page_text",
            "ocr_page_complete", "critical_spans",
        })
        case_ref = _text(page["case_ref"])
        locator = _text(page["page_locator"])
        _require((case_ref, locator) not in seen_pages)
        seen_pages.add((case_ref, locator))
        _require(type(page["document_version"]) is int and page["document_version"] >= 1)
        _hash(page["source_file_sha256"])
        _hash(page["extraction_sha256"])
        ref = page["reference_page_text"]
        ocr = page["ocr_page_text"]
        _require(type(ref) is str and type(ocr) is str)
        _require(len(ref) <= _MAX_TEXT_CHARS and len(ocr) <= _MAX_TEXT_CHARS)
        _require(type(page["ocr_page_complete"]) is bool)
        spans = page["critical_spans"]
        _require(type(spans) is list and 1 <= len(spans) <= _MAX_SPANS_PER_PAGE)
        seen_spans: set[str] = set()
        for span in spans:
            _keys(span, {"span_ref", "kind", "literal", "expected_present", "search_exact_hit"})
            name = _text(span["span_ref"])
            _require(name not in seen_spans)
            seen_spans.add(name)
            kind = _text(span["kind"])
            _require(kind in KINDS)
            literal = _text(span["literal"], length=2000)
            expected = span["expected_present"]
            search = span["search_exact_hit"]
            _require(type(expected) is bool and (search is None or type(search) is bool))
            _require((literal in ref) is expected)
            _require(expected or search is None)
            # Search-only success with no such text in complete persisted OCR
            # signals a source-lineage/provenance inconsistency: refuse report.
            if expected and page["ocr_page_complete"] and literal not in ocr:
                _require(search is not True)
            for bucket in (overall, by_kind[kind]):
                if expected:
                    bucket["reference_positive"] += 1
                    if not page["ocr_page_complete"]:
                        bucket["ocr_positive_unknown"] += 1
                        continue
                    bucket["ocr_positive_measured"] += 1
                    if literal not in ocr:
                        bucket["ocr_exact_missing"] += 1
                    else:
                        bucket["ocr_exact_found"] += 1
                        if search is None:
                            bucket["search_unmeasured_given_ocr_found"] += 1
                        else:
                            bucket["search_measured_given_ocr_found"] += 1
                            bucket["search_exact_found" if search else "search_exact_missing"] += 1
                else:
                    bucket["reference_negative_controls"] += 1
                    if not page["ocr_page_complete"]:
                        bucket["ocr_negative_unknown"] += 1
                        continue
                    bucket["ocr_negative_measured"] += 1
                    if literal in ocr:
                        bucket["ocr_false_insertion"] += 1

    def summarize(counts: dict[str, int]) -> dict[str, Any]:
        n = counts["ocr_positive_measured"]
        found = counts["ocr_exact_found"]
        neg = counts["ocr_negative_measured"]
        search_n = counts["search_measured_given_ocr_found"]
        return {
            **counts,
            "ocr_exact_literal_recall_measured_only": round(found / n, 4) if n else None,
            "ocr_exact_literal_recall_wilson95_descriptive": _wilson(found, n),
            "false_insertion_rate_on_negative_controls": (
                round(counts["ocr_false_insertion"] / neg, 4) if neg else None
            ),
            "search_exact_retrieval_given_ocr_literal_present": (
                round(counts["search_exact_found"] / search_n, 4) if search_n else None
            ),
        }

    return {
        "schema_version": 1,
        "pages_measured_or_screened": len(records),
        "measurement_kind": "descriptive_exact_literal_only",
        "source_and_extraction_hashes": "format_checked_not_source_attested",
        "reference_transcript_independently_adjudicated": False,
        "negation_scope_semantics_verified": False,
        "human_bilingual_review_completed": False,
        "pilot_accepted": False,
        "overall": summarize(overall),
        "by_kind": {k: summarize(by_kind[k]) for k in KINDS},
        "warning": (
            "These are exact-literal, self-supplied offline observations only. "
            "No source provenance, permission, sample independence or expert "
            "adjudication was verified. No production or pilot decision is authorized."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline descriptive OCR validation; no source text output")
    parser.add_argument("--input", required=True, type=Path, help="Local JSON; permission-cleared input only")
    args = parser.parse_args(argv)
    try:
        # Read locally without logging the file path or the source content.
        if args.input.stat().st_size > 30_000_000:
            raise ValueError("oversized")
        with args.input.open("r", encoding="utf-8") as stream:
            obj = json.load(stream)
        report = evaluate_local_study(obj)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        print("ocr_validation_input_rejected", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

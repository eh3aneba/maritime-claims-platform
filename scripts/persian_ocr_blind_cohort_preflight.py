"""Private-local, structural blind-cohort admission preflight (never GO).

Compares pseudonymous manifest with the exact study JSON used by the
separate literal metrics tool. No private source text, identifiers or paths
appear in CLI output. Split disjointness cannot prove unseen-source status.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.persian_ocr_local_validation_metrics import (
    KINDS, _reject_duplicate_json_keys, evaluate_local_study,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_TYPES = {"native_scan", "photograph", "scanned_pdf", "born_digital"}
_SCRIPT_TYPES = {"persian", "mixed_persian_latin"}
_SPLITS = {"development", "blind_holdout"}
_MAX_ITEMS = 2000


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("blind_cohort_structural_admission_rejected")


def _strict_keys(value: Any, keys: set[str]) -> None:
    _require(type(value) is dict and set(value) == keys)


def _opaque_id(value: Any) -> str:
    _require(type(value) is str and 1 <= len(value) <= 100)
    return value


def _digest(value: Any) -> str:
    _require(type(value) is str and _SHA256.fullmatch(value) is not None)
    return value


def check_blind_cohort(manifest: Any, measurements: Any) -> dict[str, Any]:
    """Refuse split collision or source mismatch; report coverage, NOT accuracy."""
    # First reject malformed actual study structure without printing any bytes.
    metric_report = evaluate_local_study(measurements)
    _strict_keys(manifest, {
        "schema_version", "protocol_ref", "minimum_blind_holdout_sources",
        "predeclared_critical_kinds", "sources",
    })
    _require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1)
    _opaque_id(manifest["protocol_ref"])
    minimum = manifest["minimum_blind_holdout_sources"]
    _require(type(minimum) is int and 1 <= minimum <= _MAX_ITEMS)
    required = manifest["predeclared_critical_kinds"]
    _require(type(required) is list and 1 <= len(required) <= len(KINDS))
    _require(all(type(k) is str and k in KINDS for k in required))
    _require(len(required) == len(set(required)))
    sources = manifest["sources"]
    _require(type(sources) is list and 2 <= len(sources) <= _MAX_ITEMS)

    split_by_case: dict[str, str] = {}
    split_by_hash: dict[str, str] = {}
    blind: dict[str, dict] = {}
    development_count = 0
    for source in sources:
        _strict_keys(source, {
            "case_ref", "source_file_sha256", "split", "source_kind", "script_mix",
            "expected_critical_kinds",
        })
        case = _opaque_id(source["case_ref"])
        digest = _digest(source["source_file_sha256"])
        split = source["split"]
        _require(type(split) is str and split in _SPLITS)
        _require(type(source["source_kind"]) is str and source["source_kind"] in _SOURCE_TYPES)
        _require(type(source["script_mix"]) is str and source["script_mix"] in _SCRIPT_TYPES)
        kinds = source["expected_critical_kinds"]
        _require(type(kinds) is list and 1 <= len(kinds) <= len(KINDS))
        _require(all(type(k) is str and k in KINDS for k in kinds))
        _require(len(kinds) == len(set(kinds)))
        # Case-level leakage matters even if a second scan has a new hash.
        _require(case not in split_by_case)
        _require(digest not in split_by_hash)
        split_by_case[case] = split
        split_by_hash[digest] = split
        if split == "development":
            development_count += 1
        else:
            blind[case] = source
    _require(development_count > 0 and len(blind) > 0)

    covered: set[str] = set()
    observed_by_kind: set[str] = set()
    for page in measurements["records"]:
        case = page["case_ref"]
        _require(case in blind)
        _require(
            page["source_file_sha256"] == blind[case]["source_file_sha256"]
        )
        # Study pages can only measure source-declared critical classes.
        allowed = set(blind[case]["expected_critical_kinds"])
        for span in page["critical_spans"]:
            _require(span["kind"] in allowed)
            if span["expected_present"]:
                observed_by_kind.add(span["kind"])
        covered.add(case)

    missing_kinds = sorted(set(required) - observed_by_kind)
    missing_sources = len(blind) - len(covered)
    # This merely tracks self-supplied, syntactically consistent inputs.
    structurally_complete = (
        len(blind) >= minimum and missing_sources == 0 and not missing_kinds
    )
    return {
        "schema_version": 1,
        "measurement_kind": "local_manifest_structure_only",
        "sources_registered_total": len(sources),
        "development_sources_registered": development_count,
        "blind_holdout_sources_registered": len(blind),
        "blind_holdout_sources_with_study_pages": len(covered),
        "blind_holdout_sources_without_study_pages": missing_sources,
        "predeclared_minimum_holdout_sources": minimum,
        "minimum_holdout_count_met": len(blind) >= minimum,
        "required_critical_kinds_count": len(required),
        "required_critical_kinds_not_observed": missing_kinds,
        "submitted_holdout_structure_complete": structurally_complete,
        "matched_source_hashes_format_and_manifest_only": True,
        "source_bytes_independently_verified": False,
        "blinding_independently_attested": False,
        "reference_transcripts_independently_adjudicated": False,
        "acceptance_thresholds_approved": False,
        "negation_scope_semantics_verified": False,
        "human_bilingual_review_completed": False,
        "pilot_accepted": False,
        "literal_metric_pages_screened": metric_report["pages_measured_or_screened"],
        "warning": (
            "Self-reported local metadata cannot prove source blinding, "
            "customer permission, correct original bytes, independent expert "
            "review or safe OCR accuracy. Structural completeness is not GO."
        ),
    }


def _read_private_json(path: Path) -> Any:
    if path.stat().st_size > 30_000_000:
        raise ValueError("too_large")
    with path.open("r", encoding="utf-8") as src:
        return json.load(src, object_pairs_hook=_reject_duplicate_json_keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline OCR blind cohort structure preflight (NO-GO always)"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--measurements", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = check_blind_cohort(
            _read_private_json(args.manifest),
            _read_private_json(args.measurements),
        )
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        print("blind_cohort_input_rejected", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

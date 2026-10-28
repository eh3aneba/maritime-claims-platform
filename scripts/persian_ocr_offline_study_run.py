"""One-command, privacy-preserving technical preflight for Persian OCR study.

This composes existing strict file-integrity, blind-cohort and critical-span
literal metrics on the same in-memory JSON objects. It does not attest
reviewers, semantic accuracy, provenance or pilot acceptance. Fail closed
on incomplete manifest coverage or invalid study observations.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.persian_ocr_blind_cohort_preflight import (
    _read_private_json,
    check_blind_cohort,
)
from scripts.persian_ocr_local_source_integrity import (
    _read_json,
    verify_source_bytes,
)
from scripts.persian_ocr_local_validation_metrics import evaluate_local_study
from scripts.persian_ocr_review_disagreement_metrics import summarize_review_observations


def evaluate_study_packet(
    *, manifest: Any, inventory: Any, measurements: Any, root: Path,
    reviews: Any | None = None,
) -> dict[str, Any]:
    """Return only aggregates, and only after *all* technical checks pass.

    Note: human-supplied inputs are assertions; a successful run is neither
    independent annotation nor a factual statement about OCR reliability.
    """
    byte_check = verify_source_bytes(manifest, inventory, root=root)
    blind_check = check_blind_cohort(manifest, measurements)
    if not blind_check["submitted_holdout_structure_complete"]:
        raise ValueError("study_cohort_structurally_incomplete")
    measurement = evaluate_local_study(measurements)
    if measurement["pages_measured_or_screened"] != blind_check["literal_metric_pages_screened"]:
        raise ValueError("study_page_count_inconsistent")

    # Optional self-supplied review observations are cross-checked against
    # exactly the same manifest and measurements before any aggregate is
    # returned. No claimed reviewer identity or human signoff is authenticated.
    review_summary = (
        summarize_review_observations(
            manifest=manifest, measurements=measurements, reviews=reviews,
        )
        if reviews is not None else None
    )

    # Report no source text, case references, hashes, paths, or identifiers.
    report = {
        "schema_version": 1,
        "measurement_kind": "local_composed_descriptive_study_only",
        "source_file_hash_verification": {
            "registered_source_files": byte_check["registered_source_files"],
            "locally_hash_matched_source_files": byte_check["locally_hash_matched_source_files"],
            "source_bytes_read_total": byte_check["source_bytes_read_total"],
            "local_source_hashes_matched": byte_check["local_source_hashes_matched"],
        },
        "blind_cohort_metadata": {
            "development_sources_registered": blind_check["development_sources_registered"],
            "blind_holdout_sources_registered": blind_check["blind_holdout_sources_registered"],
            "blind_holdout_sources_with_study_pages": blind_check["blind_holdout_sources_with_study_pages"],
            "blind_holdout_sources_without_study_pages": blind_check["blind_holdout_sources_without_study_pages"],
            "required_critical_kinds_not_observed": blind_check["required_critical_kinds_not_observed"],
            "self_reported_cohort_structure_complete": True,
        },
        "literal_metrics": {
            "pages_measured_or_screened": measurement["pages_measured_or_screened"],
            "overall": measurement["overall"],
            "by_kind": measurement["by_kind"],
        },
        "source_provenance_independently_attested": False,
        "customer_permission_verified": False,
        "blinding_independently_attested": False,
        "reference_transcripts_independently_adjudicated": False,
        "human_bilingual_review_completed": False,
        "negation_scope_semantics_verified": False,
        "acceptance_thresholds_approved": False,
        "critical_fact_authorization_granted": False,
        "pilot_accepted": False,
        "warning": (
            "Locally supplied files match locally supplied hashes and study "
            "metadata satisfies structural checks. This is NOT independent "
            "OCR accuracy, corpus blinding, permission, reviewer approval "
            "or authorization to process real claims."
        ),
    }
    if review_summary is not None:
        counts = review_summary["overall"]
        # Observed completeness only means rows were supplied by the
        # operator, NOT independently performed source-image comparisons.
        report["self_reported_reviewer_observations"] = review_summary
        report["submitted_review_rows_structurally_complete"] = (
            counts["reference_spans_with_no_review_row"] == 0
            and counts["specialist_adjudication_record_missing"] == 0
        )
        report["independent_human_signoff_granted"] = False
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local OCR study: byte hashes + blind metadata + literal metrics; NO-GO"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--reviews", type=Path, default=None,
        help="Optional private, self-reported dual-review observations (NOT approval)",
    )
    args = parser.parse_args(argv)

    try:
        manifest = _read_json(args.manifest)
        inventory = _read_json(args.inventory)
        measurements = _read_private_json(args.measurements)
        report = evaluate_study_packet(
            manifest=manifest,
            inventory=inventory,
            measurements=measurements,
            root=args.source_root,
            reviews=_read_private_json(args.reviews) if args.reviews is not None else None,
        )
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        # Never leak a private filename or page text in stderr.
        print("ocr_offline_study_packet_rejected", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

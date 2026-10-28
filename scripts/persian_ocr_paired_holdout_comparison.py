"""Private-local *paired* Persian OCR holdout comparison; no winner or pilot GO.

Both transcripts and references are operator-supplied. Source file hashes are
verified against locally supplied bytes; origin, true blindness, semantic scope
and reviewer independence are NOT established. Never print texts or IDs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.persian_ocr_blind_cohort_preflight import (
    _read_private_json, check_blind_cohort,
)
from scripts.persian_ocr_local_source_integrity import _read_json, verify_source_bytes
from scripts.persian_ocr_local_validation_metrics import KINDS, evaluate_local_study


def _require(ok: bool) -> None:
    if not ok:
        raise ValueError("paired_ocr_study_not_comparable")


def _page_index(study: dict) -> dict[tuple[str, str], dict]:
    return {
        (page["case_ref"], page["page_locator"]): page
        for page in study["records"]
    }


def _spans(page: dict) -> dict[str, dict]:
    return {span["span_ref"]: span for span in page["critical_spans"]}


def _blank_counts() -> dict[str, int]:
    return {
        "reference_positive_spans": 0,
        "both_literal_present": 0,
        "both_literal_missing": 0,
        "candidate_recovered_baseline_missing": 0,
        "candidate_lost_baseline_present": 0,
        "baseline_or_candidate_unmeasured": 0,
        "negative_control_spans": 0,
        "negative_control_clear_both": 0,
        "negative_control_inserted_both": 0,
        "candidate_new_false_insertion": 0,
        "candidate_removed_false_insertion": 0,
        "negative_control_unmeasured": 0,
    }


def _label(page: dict, span: dict) -> str:
    if not page["ocr_page_complete"]:
        return "unmeasured"
    present = span["literal"] in page["ocr_page_text"]
    return "present" if present else "absent"


def compare_paired_ocr_studies(
    *, manifest: Any, inventory: Any,
    baseline: Any, candidate: Any, root: Path,
) -> dict[str, Any]:
    """Only compare identical page-level sources and predeclared critical spans."""
    # No partial result if either packet, declared source file or holdout
    # structure is incomplete or contradictory.
    files = verify_source_bytes(manifest, inventory, root=root)
    left_cohort = check_blind_cohort(manifest, baseline)
    right_cohort = check_blind_cohort(manifest, candidate)
    _require(left_cohort["submitted_holdout_structure_complete"] is True)
    _require(right_cohort["submitted_holdout_structure_complete"] is True)
    left = evaluate_local_study(baseline)
    right = evaluate_local_study(candidate)
    left_pages = _page_index(baseline)
    right_pages = _page_index(candidate)
    _require(set(left_pages) == set(right_pages))

    # The cohort preflight requires global kind coverage, but global
    # coverage alone can hide a completely unmeasured category on one
    # particular declared holdout source. Demand each source's own
    # preregistered classes be represented by at least one positive or
    # negative-control span across that source's submitted pages.
    expected_kinds_by_source = {
        entry["case_ref"]: set(entry["expected_critical_kinds"])
        for entry in manifest["sources"]
        if entry["split"] == "blind_holdout"
    }
    covered_kinds_by_source = {
        case_ref: set() for case_ref in expected_kinds_by_source
    }

    overall = _blank_counts()
    by_kind = {kind: _blank_counts() for kind in KINDS}
    for key, source in left_pages.items():
        alternative = right_pages[key]
        for field in (
            "document_version", "source_file_sha256", "reference_page_text",
        ):
            _require(source[field] == alternative[field])
        source_spans = _spans(source)
        candidate_spans = _spans(alternative)
        _require(set(source_spans) == set(candidate_spans))
        if source["ocr_page_text"] != alternative["ocr_page_text"]:
            # Source-text lineage hashes cannot be identical for two
            # different observed OCR transcripts of the same page.
            # Hashes are still operator-supplied, not independently proven.
            _require(source["extraction_sha256"] != alternative["extraction_sha256"])
        covered_kinds_by_source[key[0]].update(
            span["kind"] for span in source_spans.values()
        )
        for span_id, critical in source_spans.items():
            tested = candidate_spans[span_id]
            for field in ("kind", "literal", "expected_present"):
                _require(critical[field] == tested[field])
            baseline_label = _label(source, critical)
            candidate_label = _label(alternative, tested)
            if critical["expected_present"]:
                if "unmeasured" in (baseline_label, candidate_label):
                    counter = "baseline_or_candidate_unmeasured"
                elif baseline_label == candidate_label == "present":
                    counter = "both_literal_present"
                elif baseline_label == candidate_label == "absent":
                    counter = "both_literal_missing"
                elif baseline_label == "absent" and candidate_label == "present":
                    counter = "candidate_recovered_baseline_missing"
                else:
                    counter = "candidate_lost_baseline_present"
                for bucket in (overall, by_kind[critical["kind"]]):
                    bucket["reference_positive_spans"] += 1
                    bucket[counter] += 1
            else:
                if "unmeasured" in (baseline_label, candidate_label):
                    counter = "negative_control_unmeasured"
                elif baseline_label == candidate_label == "absent":
                    counter = "negative_control_clear_both"
                elif baseline_label == candidate_label == "present":
                    counter = "negative_control_inserted_both"
                elif baseline_label == "absent" and candidate_label == "present":
                    counter = "candidate_new_false_insertion"
                else:
                    counter = "candidate_removed_false_insertion"
                for bucket in (overall, by_kind[critical["kind"]]):
                    bucket["negative_control_spans"] += 1
                    bucket[counter] += 1

    _require(all(
        expected_kinds.issubset(covered_kinds_by_source[case_ref])
        for case_ref, expected_kinds in expected_kinds_by_source.items()
    ))

    return {
        "schema_version": 1,
        "measurement_kind": "self_supplied_paired_holdout_literal_comparison_only",
        "all_declared_source_kind_classes_present_in_submitted_spans": True,
        "source_files_locally_hash_matched": files["locally_hash_matched_source_files"],
        "pages_matched": len(left_pages),
        "comparison": {"overall": overall, "by_kind": by_kind},
        "baseline_literal_metrics": {"overall": left["overall"], "by_kind": left["by_kind"]},
        "candidate_literal_metrics": {"overall": right["overall"], "by_kind": right["by_kind"]},
        "same_declared_sources_and_reference_spans": True,
        "file_origin_independently_attested": False,
        "blinding_independently_attested": False,
        "reference_transcripts_independently_adjudicated": False,
        "human_bilingual_review_completed": False,
        "negation_scope_semantics_verified": False,
        "candidate_automatically_selected": False,
        "production_ocr_changed": False,
        "acceptance_thresholds_approved": False,
        "critical_fact_authorization_granted": False,
        "pilot_accepted": False,
        "warning": (
            "Paired literal observations are on operator-supplied OCR text and "
            "self-declared reference labels. Recovery of a token on the same "
            "pages does not prove negation scope, accuracy on unseen scans, "
            "independent expert approval or authority to change production."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline matched-source Persian OCR candidate diagnostic; never GO",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = compare_paired_ocr_studies(
            manifest=_read_json(args.manifest),
            inventory=_read_json(args.inventory),
            baseline=_read_private_json(args.baseline),
            candidate=_read_private_json(args.candidate),
            root=args.source_root,
        )
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        print("paired_persian_ocr_study_rejected", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Private-local, descriptive disagreement ledger for bilingual OCR review.

The input is an OPERATOR-SUPPLIED record of two purported reviewer opinions,
NOT proof of their identity, independence, direct source comparison, an
authenticated adjudication, semantic correctness or acceptance. Outputs
aggregates only; never prints source text, pseudo-identifiers or raw hashes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.persian_ocr_blind_cohort_preflight import (
    _opaque_id, _read_private_json, _strict_keys, check_blind_cohort,
)
from scripts.persian_ocr_local_validation_metrics import KINDS, evaluate_local_study

_FINDINGS = {"meaning_preserved", "material_meaning_changed", "source_unreadable"}
_MAX_ROWS = 200_000


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("invalid_or_incomplete_reviewer_observation_input")


def _reviewer(value: Any) -> tuple[str, str]:
    _strict_keys(value, {"reviewer_ref", "finding"})
    name = _opaque_id(value["reviewer_ref"])
    finding = value["finding"]
    _require(type(finding) is str and finding in _FINDINGS)
    return name, finding


def _adjudication(value: Any) -> tuple[str, str] | None:
    if value is None:
        return None
    _strict_keys(value, {"specialist_ref", "finding"})
    name = _opaque_id(value["specialist_ref"])
    finding = value["finding"]
    _require(type(finding) is str and finding in _FINDINGS)
    return name, finding


def _blank() -> dict[str, int]:
    return {
        "reference_positive_spans": 0,
        "two_assessment_rows_supplied": 0,
        "reference_spans_with_no_review_row": 0,
        "reviewers_agreed": 0,
        "reviewers_disagreed": 0,
        "any_reviewer_reported_material_change": 0,
        "any_reviewer_reported_unreadable_source": 0,
        "specialist_adjudication_required": 0,
        "specialist_adjudication_record_supplied": 0,
        "specialist_adjudication_record_missing": 0,
        "adjudicator_reported_meaning_preserved": 0,
        "adjudicator_reported_material_change": 0,
        "adjudicator_reported_unreadable_source": 0,
    }


def summarize_review_observations(
    *, manifest: Any, measurements: Any, reviews: Any,
) -> dict[str, Any]:
    """Cross-bind reviewer claims to complete planned holdout critical spans."""
    study = evaluate_local_study(measurements)
    cohort = check_blind_cohort(manifest, measurements)
    _require(cohort["submitted_holdout_structure_complete"])
    _strict_keys(reviews, {"schema_version", "protocol_ref", "rows"})
    _require(type(reviews["schema_version"]) is int and reviews["schema_version"] == 1)
    _require(_opaque_id(reviews["protocol_ref"]) == manifest["protocol_ref"])
    rows = reviews["rows"]
    _require(type(rows) is list and len(rows) <= _MAX_ROWS)

    indexed: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    for page in measurements["records"]:
        for span in page["critical_spans"]:
            if not span["expected_present"]:
                continue
            key = (page["case_ref"], page["page_locator"], span["span_ref"])
            _require(key not in indexed)
            indexed[key] = (
                span["kind"],
                page["source_file_sha256"],
                page["extraction_sha256"],
            )
    overall = _blank()
    categories = {kind: _blank() for kind in KINDS}
    for kind, _, _ in indexed.values():
        overall["reference_positive_spans"] += 1
        categories[kind]["reference_positive_spans"] += 1

    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        _strict_keys(row, {
            "case_ref", "page_locator", "span_ref", "source_file_sha256",
            "extraction_sha256", "reviewer_one", "reviewer_two",
            "specialist_adjudication",
        })
        key = (
            _opaque_id(row["case_ref"]),
            _opaque_id(row["page_locator"]),
            _opaque_id(row["span_ref"]),
        )
        _require(key in indexed and key not in seen)
        seen.add(key)
        kind, source_hash, extraction_hash = indexed[key]
        _require(row["source_file_sha256"] == source_hash)
        _require(row["extraction_sha256"] == extraction_hash)
        reviewer_a, verdict_a = _reviewer(row["reviewer_one"])
        reviewer_b, verdict_b = _reviewer(row["reviewer_two"])
        _require(reviewer_a != reviewer_b)
        adjudication = _adjudication(row["specialist_adjudication"])
        # Any potential material error or illegible scan requires specialist
        # consideration. The same applies to two different judgments.
        required = (
            verdict_a != verdict_b
            or verdict_a != "meaning_preserved"
            or verdict_b != "meaning_preserved"
        )
        if adjudication is not None:
            _require(required)
            _require(adjudication[0] not in (reviewer_a, reviewer_b))
        for bucket in (overall, categories[kind]):
            bucket["two_assessment_rows_supplied"] += 1
            bucket["reviewers_agreed" if verdict_a == verdict_b else "reviewers_disagreed"] += 1
            if "material_meaning_changed" in (verdict_a, verdict_b):
                bucket["any_reviewer_reported_material_change"] += 1
            if "source_unreadable" in (verdict_a, verdict_b):
                bucket["any_reviewer_reported_unreadable_source"] += 1
            if required:
                bucket["specialist_adjudication_required"] += 1
                if adjudication is None:
                    bucket["specialist_adjudication_record_missing"] += 1
                else:
                    bucket["specialist_adjudication_record_supplied"] += 1
                    bucket[{
                        "meaning_preserved": "adjudicator_reported_meaning_preserved",
                        "material_meaning_changed": "adjudicator_reported_material_change",
                        "source_unreadable": "adjudicator_reported_unreadable_source",
                    }[adjudication[1]]] += 1

    def finalize(bucket: dict[str, int]) -> dict[str, Any]:
        bucket["reference_spans_with_no_review_row"] = (
            bucket["reference_positive_spans"] - bucket["two_assessment_rows_supplied"]
        )
        observed = bucket["two_assessment_rows_supplied"]
        return {
            **bucket,
            "reported_pairwise_agreement_rate": (
                round(bucket["reviewers_agreed"] / observed, 4) if observed else None
            ),
        }

    return {
        "schema_version": 1,
        "measurement_kind": "self_reported_reviewer_observation_counts_only",
        "planned_critical_reference_positive_spans": len(indexed),
        "pages_screened": study["pages_measured_or_screened"],
        "overall": finalize(overall),
        "by_kind": {kind: finalize(bucket) for kind, bucket in categories.items()},
        "reviewer_identity_independently_verified": False,
        "two_reviewers_actually_compared_scans_verified": False,
        "adjudicator_identity_or_authority_verified": False,
        "verbatim_reference_adjudicated": False,
        "negation_scope_accuracy_verified": False,
        "human_bilingual_review_completed": False,
        "critical_fact_authorization_granted": False,
        "pilot_accepted": False,
        "warning": (
            "Reviewer and specialist verdicts are self-supplied observations, "
            "not independently authenticated evidence. Any disagreement, "
            "material error or unreadable page needs controlled H&M review. "
            "Reported agreement does not establish OCR accuracy or pilot GO."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline OCR reviewer disagreement counts; no GO")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--measurements", required=True, type=Path)
    parser.add_argument("--reviews", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = summarize_review_observations(
            manifest=_read_private_json(args.manifest),
            measurements=_read_private_json(args.measurements),
            reviews=_read_private_json(args.reviews),
        )
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        print("ocr_review_observations_rejected", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

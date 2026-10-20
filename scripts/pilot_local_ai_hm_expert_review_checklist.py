"""Fixed, unfilled independent H&M expert review checklist for invented fixtures.

This is an operator planning aid, not an H&M judgment, model assessment,
reviewer evidence capture, real claim loader or acceptance decision. The CLI
has no user input fields, file writes, inference, HTTP or external services.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from scripts.pilot_local_ai_hm_fixture_matrix import scenario_names

_COMMON_CRITERIA = (
    "source_identity_and_version_correct",
    "verbatim_excerpt_exists_in_attributed_source",
    "critical_evidence_omissions_assessed",
    "source_claim_not_misrepresented_as_verified_fact",
    "no_causation_negligence_or_coverage_inferred_without_evidence",
)
_SCENARIO_CRITERIA = {
    "complete_records": (
        "supplied_records_not_mistaken_for_verified_records",
        "alarm_and_shutdown_are_distinguished",
    ),
    "missing_engine_records": (
        "not_supplied_not_mistaken_for_nonexistent",
        "unknown_document_existence_preserved",
    ),
    "conflicting_alarm_times": (
        "both_reported_alarm_times_separately_attributed",
        "unresolved_conflict_not_silently_resolved",
    ),
}


def fixed_unfilled_expert_review_checklist() -> dict[str, Any]:
    """Return only code-owned field names, never sources, labels or people."""
    names = scenario_names()
    if tuple(_SCENARIO_CRITERIA) != names:
        raise ValueError("unreviewed_synthetic_scenario_drift")
    return {
        "scope": "synthetic_expert_review_planning_only",
        "review_packet_version": "hm-expert-checklist-v1",
        "cases": [
            {
                "scenario": name,
                "source_record_ids": ["S1", "S2", "S3"],
                "criteria": list(_COMMON_CRITERIA + _SCENARIO_CRITERIA[name]),
                "independent_expert_assigned": False,
                "independent_expert_labels_collected": False,
                "independent_expert_adjudication_completed": False,
                "review_outcome": "pending",
            }
            for name in names
        ],
        "blinded_review_process_verified": False,
        "real_model_outputs_reviewed": False,
        "reviewer_identity_attested": False,
        "expert_reference_approved": False,
        "customer_evidence_reviewed": False,
        "pilot_accepted": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--print-unfilled-synthetic-hm-expert-checklist"]:
        print("synthetic_expert_review_explicit_opt_in_required")
        return 2
    try:
        packet = fixed_unfilled_expert_review_checklist()
        print(json.dumps(packet, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception:
        print("synthetic_expert_review_checklist_unavailable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

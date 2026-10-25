"""Neutral phase-one H&M expert review packet using ONLY invented sources.

No scenario labels, source-gate anchors, baseline, model response or rubric
answers are emitted. Does not contact Ollama, inspect real claims, store
reviews or claim that an expert performed a blinded review.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

from scripts.pilot_local_ai_hm_fixture_matrix import scenario_names
from scripts.pilot_local_ai_hm_source_only_review_packet import (
    fixed_blinded_source_review_packet,
)

_CASE_CODES = ("CASE-01", "CASE-02", "CASE-03")
_IDS = ("S1", "S2", "S3")
_KINDS = frozenset({"event_notice", "reported_statement", "intake_status"})
_NEUTRAL_QUESTIONS = (
    "What does each attributed source expressly report, and what is its version?",
    "Which statements are independently corroborated by this packet, if any?",
    "What uncertainties, contradictions or evidence gaps remain?",
    "Which conclusions would need additional technical, documentary or policy evidence?",
)


def fixed_neutral_blind_hm_phase_one_packet() -> dict[str, Any]:
    """Sanitize fixed fixture sources into an unlabeled non-approving packet."""
    source = fixed_blinded_source_review_packet()
    names = scenario_names()
    if (
        type(source) is not dict
        or source.get("scope") != "invented_hm_source_only_blind_review_packet"
        or source.get("packet_version") != "hm-invented-sources-v1"
        or type(source.get("cases")) is not list
        or len(source["cases"]) != len(_CASE_CODES)
        or names != ("complete_records", "missing_engine_records", "conflicting_alarm_times")
        or any(source.get(flag) is not False for flag in (
            "source_packet_digest_independently_attested",
            "includes_model_outputs", "includes_model_reference_candidate",
            "contains_real_customer_evidence", "reviewer_blindness_verified",
            "independent_expert_labels_collected", "expert_reference_approved",
            "pilot_accepted",
        ))
    ):
        raise ValueError("untrusted_neutral_source_packet")
    canonical_source = json.dumps(
        source["cases"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    expected_hash = hashlib.sha256(canonical_source.encode("utf-8")).hexdigest()
    if source.get("source_packet_sha256_observed") != expected_hash:
        raise ValueError("untrusted_neutral_source_packet")

    cases: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        case = source["cases"][index]
        if (
            type(case) is not dict
            or set(case) != {
                "scenario", "source_records", "unanswered_review_criteria",
                "review_outcome", "expert_reference_approved",
            }
            or case["scenario"] != name
            or case["review_outcome"] != "pending"
            or case["expert_reference_approved"] is not False
            or type(case["unanswered_review_criteria"]) is not list
            or type(case["source_records"]) is not list
            or len(case["source_records"]) != len(_IDS)
        ):
            raise ValueError("untrusted_neutral_source_packet")
        records = []
        for j, src in enumerate(case["source_records"]):
            if (
                type(src) is not dict
                or set(src) != {
                    "source_id", "source_version", "kind", "invented_source_text",
                }
                or src["source_id"] != _IDS[j]
                or src["source_version"] != "v1"
                or type(src["kind"]) is not str
                or src["kind"] not in _KINDS
                or type(src["invented_source_text"]) is not str
                or not src["invented_source_text"].startswith("Synthetic ")
                or not 1 <= len(src["invented_source_text"]) <= 512
            ):
                raise ValueError("untrusted_neutral_source_packet")
            records.append({
                "source_id": src["source_id"],
                "source_version": src["source_version"],
                "kind": src["kind"],
                "invented_source_text": src["invented_source_text"],
            })
        cases.append({"case_code": _CASE_CODES[index], "source_records": records})

    # Hash only the neutral output inputs; an observed digest is NOT custody
    # attestation, a signature or proof of reviewer blindness.
    canonical = json.dumps(
        {"cases": cases, "review_questions": _NEUTRAL_QUESTIONS},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return {
        "scope": "invented_hm_neutral_blind_phase_one_only",
        "packet_version": "hm-neutral-phase-one-v1",
        "packet_sha256_observed": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "digest_independently_attested": False,
        "reviewer_blindness_verified": False,
        "expert_labels_collected": False,
        "model_outputs_included": False,
        "baseline_answers_included": False,
        "review_completed": False,
        "pilot_accepted": False,
        "review_questions": list(_NEUTRAL_QUESTIONS),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--print-neutral-blind-synthetic-hm-phase-one"]:
        print("neutral_blind_synthetic_hm_explicit_opt_in_required")
        return 2
    try:
        packet = fixed_neutral_blind_hm_phase_one_packet()
        print(json.dumps(packet, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception:
        print("neutral_blind_synthetic_hm_packet_unavailable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

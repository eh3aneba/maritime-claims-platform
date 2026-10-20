"""Opt-in source-only packet for independently reviewing three invented H&M cases.

Contains invented fixture texts and a blank question checklist, but NO model
output, machine-generated answers, reference candidate or human approval.
No customer files, arbitrary input, network, persistence or remote AI.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

from scripts.pilot_local_ai_hm_expert_review_checklist import (
    fixed_unfilled_expert_review_checklist,
)
from scripts.pilot_local_ai_hm_fixture_matrix import (
    scenario_names, synthetic_source_catalog,
)

_EXPECTED_SOURCE_IDS = ("S1", "S2", "S3")
_SOURCE_KEYS = frozenset({"kind", "version", "body"})
_SOURCE_KINDS = frozenset({"event_notice", "reported_statement", "intake_status"})
_MAX_SYNTHETIC_BODY_CHARS = 512


def fixed_blinded_source_review_packet() -> dict[str, Any]:
    """Return only versioned, literal, invented source records and blank criteria."""
    checklist = fixed_unfilled_expert_review_checklist()
    names = scenario_names()
    if (
        type(checklist) is not dict
        or checklist.get("scope") != "synthetic_expert_review_planning_only"
        or checklist.get("expert_reference_approved") is not False
        or checklist.get("reviewer_identity_attested") is not False
        or checklist.get("blinded_review_process_verified") is not False
        or checklist.get("pilot_accepted") is not False
    ):
        raise ValueError("untrusted_review_checklist")
    rows = checklist.get("cases")
    if type(rows) is not list or len(rows) != 3:
        raise ValueError("untrusted_review_checklist")

    cases: list[dict[str, Any]] = []
    for idx, name in enumerate(names):
        current = rows[idx]
        if (
            type(current) is not dict
            or current.get("scenario") != name
            or current.get("source_record_ids") != list(_EXPECTED_SOURCE_IDS)
            or current.get("review_outcome") != "pending"
            or current.get("independent_expert_assigned") is not False
            or current.get("independent_expert_labels_collected") is not False
            or current.get("independent_expert_adjudication_completed") is not False
            or type(current.get("criteria")) is not list
            or not 1 <= len(current["criteria"]) <= 16
            or any(type(key) is not str or not key.isidentifier()
                   for key in current["criteria"])
        ):
            raise ValueError("untrusted_review_checklist")
        catalog = synthetic_source_catalog(name)
        if type(catalog) is not dict or tuple(catalog) != _EXPECTED_SOURCE_IDS:
            raise ValueError("synthetic_source_catalog_drift")
        sources = []
        for source_id in _EXPECTED_SOURCE_IDS:
            source = catalog[source_id]
            if (
                type(source) is not dict or set(source) != _SOURCE_KEYS
                or source["kind"] not in _SOURCE_KINDS
                or source["version"] != "v1"
                or type(source["body"]) is not str
                or not source["body"].startswith("Synthetic ")
                or not 1 <= len(source["body"]) <= _MAX_SYNTHETIC_BODY_CHARS
            ):
                raise ValueError("synthetic_source_catalog_drift")
            sources.append({
                "source_id": source_id,
                "source_version": source["version"],
                "kind": source["kind"],
                "invented_source_text": source["body"],
            })
        cases.append({
            "scenario": name,
            "source_records": sources,
            "unanswered_review_criteria": list(current["criteria"]),
            "review_outcome": "pending",
            "expert_reference_approved": False,
        })

    # Stable packet comparison only, not a cryptographic source attestation.
    canonical = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "scope": "invented_hm_source_only_blind_review_packet",
        "packet_version": "hm-invented-sources-v1",
        "source_packet_sha256_observed": digest,
        "source_packet_digest_independently_attested": False,
        "includes_model_outputs": False,
        "includes_model_reference_candidate": False,
        "contains_real_customer_evidence": False,
        "reviewer_blindness_verified": False,
        "independent_expert_labels_collected": False,
        "expert_reference_approved": False,
        "pilot_accepted": False,
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--print-invented-hm-source-only-packet"]:
        print("synthetic_source_packet_explicit_opt_in_required")
        return 2
    try:
        packet = fixed_blinded_source_review_packet()
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception:
        print("synthetic_source_packet_unavailable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

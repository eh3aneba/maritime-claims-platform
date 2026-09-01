from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.claims.models import Claim
from app.modules.recovery_timebar import service_core as core
from app.modules.rules.marine_service import latest_marine_rule_summary


_original_source_state = core._source_state
_original_marine_sources = core._marine_sources


def _marine_recovery_rows(db: Session, claim: Claim) -> list[dict[str, Any]]:
    """Return downstream marine-rule signals after respecting human dispositions.

    A dismissed / not-applicable rule evaluation must not continue to generate a
    recovery lead. Accepted evaluations retain their deterministic meaning. A
    human edit may refine the candidate implication / recommended action while
    preserving the immutable underlying evaluation hash and decision lineage.
    """
    summary = latest_marine_rule_summary(db, claim=claim)
    rows = list(summary.get("marine_rule_evaluations") or [])
    output: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") not in {"triggered", "insufficient_evidence"}:
            continue
        if not (row.get("rule_id") == "TECH-002" or row.get("family") in {"emergency_services", "charterparty"}):
            continue

        decision = dict(row.get("latest_decision") or {})
        action = decision.get("action")
        if action in {"dismiss", "not_applicable"}:
            continue

        current = dict(row)
        if action == "edit":
            if decision.get("edited_candidate_implication"):
                current["candidate_implication"] = decision["edited_candidate_implication"]
            if decision.get("edited_recommended_action"):
                current["recommended_action"] = decision["edited_recommended_action"]
        if decision:
            current["human_disposition"] = {
                "action": action,
                "decision_number": decision.get("decision_number"),
                "decision_hash": decision.get("decision_hash"),
            }
        output.append(current)
    return output


def _source_state(
    claim: Claim,
    facts,
    marine_rows: list[dict[str, Any]],
    evaluation_date,
) -> dict[str, Any]:
    state = _original_source_state(claim, facts, marine_rows, evaluation_date)
    state["marine_recovery_rows"] = [
        {
            "rule_id": row.get("rule_id"),
            "rule_version": row.get("rule_version"),
            "status": row.get("status"),
            "evaluation_hash": row.get("evaluation_hash"),
            "human_disposition_action": (row.get("human_disposition") or {}).get("action"),
            "human_disposition_hash": (row.get("human_disposition") or {}).get("decision_hash"),
        }
        for row in marine_rows
    ]
    return state


def _marine_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = _original_marine_sources(rows)
    for ref, row in zip(refs, rows, strict=True):
        disposition = row.get("human_disposition")
        if disposition:
            ref["human_disposition"] = dict(disposition)
    return refs


# Patch the preserved implementation at its narrow extension points. Functions
# defined in service_core resolve these module globals at runtime, so all proven
# 12C persistence / hashing / decision behavior remains unchanged.
core._marine_recovery_rows = _marine_recovery_rows
core._source_state = _source_state
core._marine_sources = _marine_sources

# Preserve the service module's established public/private surface for routers,
# tests and downstream integrations while keeping the human-control delta small.
for _name in dir(core):
    if not _name.startswith("__") and _name not in {"_marine_recovery_rows", "_source_state", "_marine_sources"}:
        globals()[_name] = getattr(core, _name)

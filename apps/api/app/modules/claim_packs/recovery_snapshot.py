from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.claims.models import Claim
from app.modules.recovery_timebar.decision_lineage import (
    DECISION_DISCLAIMER,
    current_decisions,
    decision_response,
)
from app.modules.recovery_timebar.maturity import (
    MATURITY_DISCLAIMER,
    counterparty_response,
    current_counterparties,
    current_scenarios,
    scenario_response,
)


RECOVERY_REPORTING_DISCLAIMER = (
    "Recovery closure/reporting is a downstream review projection of explicit human records only. "
    "It does not determine liability, legal entitlement, recoverability, governing law, an authoritative time-bar, "
    "settlement, payment, reserve adequacy or claim closure. A human handler remains responsible for any decision to "
    "pursue, discontinue, settle or close a recovery path or the claim."
)


def build_recovery_snapshot(db: Session, *, claim: Claim) -> dict[str, Any]:
    counterparties = [counterparty_response(db, row) for row in current_counterparties(db, claim=claim)]
    scenarios = [scenario_response(db, row) for row in current_scenarios(db, claim=claim)]
    decisions = [decision_response(db, claim=claim, row=row) for row in current_decisions(db, claim=claim)]

    decision_by_counterparty = {str(row["counterparty_id"]): row for row in decisions}
    unreviewed_counterparties = [
        row for row in counterparties if str(row["id"]) not in decision_by_counterparty
    ]
    stale_decisions = [
        row for row in decisions if row["context_state_status"] in {"stale", "source_unavailable"}
    ]
    open_decisions = [row for row in decisions if row["disposition"] in {"pursue", "monitor"}]
    terminal_human_decisions = [
        row for row in decisions if row["disposition"] in {"do_not_pursue", "close"}
    ]
    stale_scenarios = [
        row for row in scenarios if row["source_state_status"] in {"stale", "source_unavailable"}
    ]
    unreviewed_scenarios = [row for row in scenarios if row.get("latest_review") is None]
    action_count = sum(len(row.get("actions", [])) for row in decisions)

    blockers: list[str] = []
    if stale_decisions:
        blockers.append("One or more current human recovery decisions are bound to stale or unavailable context.")
    if stale_scenarios:
        blockers.append("One or more current time-bar scenarios are bound to stale or unavailable source context.")
    if unreviewed_counterparties:
        blockers.append("One or more current recovery counterparties have no explicit human pursuit disposition.")
    if unreviewed_scenarios:
        blockers.append("One or more current time-bar scenarios have no human/legal review record.")
    if open_decisions:
        blockers.append("One or more human recovery dispositions remain pursue/monitor.")

    if stale_decisions or stale_scenarios:
        human_closure_review_state = "attention_required"
    elif open_decisions or unreviewed_counterparties or unreviewed_scenarios:
        human_closure_review_state = "open_recovery_paths"
    elif counterparties or scenarios or terminal_human_decisions:
        human_closure_review_state = "no_open_recovery_path_recorded"
    else:
        human_closure_review_state = "no_recovery_path_recorded"

    return {
        "authority": "downstream_human_record_projection_only",
        "disclaimer": RECOVERY_REPORTING_DISCLAIMER,
        "maturity_disclaimer": MATURITY_DISCLAIMER,
        "decision_disclaimer": DECISION_DISCLAIMER,
        "human_closure_review_state": human_closure_review_state,
        "closure_review_blockers": blockers,
        "counterparties": counterparties,
        "timebar_scenarios": scenarios,
        "decisions": decisions,
        "summary": {
            "counterparty_count": len(counterparties),
            "timebar_scenario_count": len(scenarios),
            "human_decision_count": len(decisions),
            "human_action_count": action_count,
            "open_human_decision_count": len(open_decisions),
            "terminal_human_decision_count": len(terminal_human_decisions),
            "stale_human_decision_count": len(stale_decisions),
            "unreviewed_counterparty_count": len(unreviewed_counterparties),
            "stale_timebar_scenario_count": len(stale_scenarios),
            "unreviewed_timebar_scenario_count": len(unreviewed_scenarios),
        },
    }

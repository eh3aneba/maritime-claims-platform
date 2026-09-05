from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.models import Claim
from app.modules.recovery_timebar import maturity as base
from app.modules.recovery_timebar.models import RecoveryCounterparty, TimebarScenario
from app.modules.recovery_timebar.schemas import TimebarScenarioReviewWrite
from app.modules.users.models import User


def _counterparty_context_state(db: Session, row: TimebarScenario) -> str | None:
    """Return a fail-closed state when a scenario's human counterparty context evolved.

    A scenario hash binds the exact counterparty record that was current when the
    scenario was created. If that logical counterparty later receives a revised
    immutable version, the old scenario remains historical evidence but must not
    be presented or reviewed as current legal context.
    """
    if row.counterparty_id is None:
        return None

    counterparty = db.scalar(
        select(RecoveryCounterparty).where(
            RecoveryCounterparty.id == row.counterparty_id,
            RecoveryCounterparty.organization_id == row.organization_id,
            RecoveryCounterparty.claim_id == row.claim_id,
        )
    )
    if counterparty is None:
        return "source_unavailable"

    latest = base._latest_counterparty(
        db,
        claim=Claim(id=row.claim_id, organization_id=row.organization_id),
        counterparty_key=counterparty.counterparty_key,
    )
    if latest is None:
        return "source_unavailable"
    if latest.id != counterparty.id or latest.record_hash != counterparty.record_hash:
        return "stale"
    return None


def scenario_context_state(db: Session, row: TimebarScenario) -> str:
    document_state = base.scenario_source_state(db, row)
    counterparty_state = _counterparty_context_state(db, row)

    if "source_unavailable" in {document_state, counterparty_state}:
        return "source_unavailable"
    if "stale" in {document_state, counterparty_state}:
        return "stale"
    return document_state


def scenario_response(db: Session, row: TimebarScenario) -> dict:
    response = base.scenario_response(db, row)
    response["source_state_status"] = scenario_context_state(db, row)
    return response


def review_scenario(
    db: Session,
    *,
    claim: Claim,
    user: User,
    scenario_id: UUID,
    payload: TimebarScenarioReviewWrite,
):
    # Lock before checking the linked counterparty so a concurrent counterparty
    # revision cannot race legal review of the prior context.
    base._lock_claim(db, claim)
    scenario = db.scalar(
        select(TimebarScenario).where(
            TimebarScenario.id == scenario_id,
            TimebarScenario.organization_id == claim.organization_id,
            TimebarScenario.claim_id == claim.id,
        )
    )
    if scenario is not None and scenario_context_state(db, scenario) in {"stale", "source_unavailable"}:
        raise ValueError(
            "Scenario context is no longer current; create a new scenario version before human/legal review"
        )
    return base.review_scenario(
        db,
        claim=claim,
        user=user,
        scenario_id=scenario_id,
        payload=payload,
    )

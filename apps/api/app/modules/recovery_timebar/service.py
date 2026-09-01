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


def _record_decision(
    db: Session,
    *,
    claim,
    evaluation,
    payload,
    user,
):
    """Persist a human disposition while binding it to the exact 12C snapshot.

    The preserved core implementation already enforces stale-evaluation, hash,
    duplicate-task and human-authority controls. This wrapper mirrors that
    behavior and fixes the persistence contract by writing the required
    ``snapshot_id`` into both the append-only decision row and its hash payload.
    """
    if evaluation.organization_id != claim.organization_id or evaluation.claim_id != claim.id:
        raise ValueError("Recovery/time-bar evaluation does not belong to this claim")
    latest_snapshot = core._latest_snapshot(db, claim=claim)
    if latest_snapshot is None or latest_snapshot.id != evaluation.snapshot_id:
        raise ValueError("Recovery/time-bar evaluation belongs to a superseded snapshot; review the latest snapshot instead")
    if payload.evaluation_hash != evaluation.evaluation_hash:
        raise ValueError("Evaluation hash does not match the immutable evaluation under review")
    if payload.convert_to_task and payload.action in {"dismiss", "not_applicable"}:
        raise ValueError("Dismissed/not-applicable evaluations cannot create controlled tasks")

    previous = core._latest_decision(db, evaluation.id)
    if payload.convert_to_task:
        existing_task = db.scalar(
            core.select(core.RecoveryTimebarDecision.converted_task_id)
            .where(
                core.RecoveryTimebarDecision.organization_id == claim.organization_id,
                core.RecoveryTimebarDecision.claim_id == claim.id,
                core.RecoveryTimebarDecision.evaluation_id == evaluation.id,
                core.RecoveryTimebarDecision.converted_task_id.is_not(None),
            )
            .order_by(core.RecoveryTimebarDecision.decision_number.desc())
            .limit(1)
        )
        if existing_task is not None:
            raise ValueError("A controlled claim task has already been created from this recovery/time-bar evaluation")

    number = (previous.decision_number + 1) if previous else 1
    task = None
    if payload.convert_to_task:
        due_date = payload.edited_due_date or evaluation.candidate_deadline
        title = (
            payload.edited_recommended_action
            if payload.action == "edit" and payload.edited_recommended_action
            else evaluation.title
        )
        description = (
            payload.edited_recommended_action
            if payload.action == "edit" and payload.edited_recommended_action
            else evaluation.recommended_action
        )
        task = core.ClaimTask(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            requirement_id=None,
            request_batch_id=None,
            assignee_id=claim.handler_id or user.id,
            title=title[:220],
            description=description,
            task_type=core.TaskType.FOLLOW_UP if evaluation.kind == "timebar" else core.TaskType.REVIEW,
            status=core.TaskStatus.OPEN,
            priority=(
                core.TaskPriority.CRITICAL
                if evaluation.urgency == "critical"
                else core.TaskPriority.HIGH
                if evaluation.urgency == "high"
                else core.TaskPriority.MEDIUM
            ),
            source=core.TaskSource.AI_SUGGESTION,
            due_date=due_date,
        )
        db.add(task)
        db.flush()

    now = core.datetime.now(core.UTC)
    decision_payload = {
        "snapshot_id": str(evaluation.snapshot_id),
        "evaluation_hash": evaluation.evaluation_hash,
        "decision_number": number,
        "action": payload.action,
        "note": payload.note.strip(),
        "edited_candidate_implication": payload.edited_candidate_implication,
        "edited_recommended_action": payload.edited_recommended_action,
        "edited_due_date": payload.edited_due_date.isoformat() if payload.edited_due_date else None,
        "converted_task_id": str(task.id) if task else None,
        "previous_decision_hash": previous.decision_hash if previous else None,
        "decided_by_id": str(user.id),
        "decided_at": now.isoformat(),
    }
    decision = core.RecoveryTimebarDecision(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        snapshot_id=evaluation.snapshot_id,
        evaluation_id=evaluation.id,
        decided_by_id=user.id,
        converted_task_id=task.id if task else None,
        decision_number=number,
        evaluation_hash=evaluation.evaluation_hash,
        action=payload.action,
        note=payload.note.strip(),
        edited_candidate_implication=payload.edited_candidate_implication,
        edited_recommended_action=payload.edited_recommended_action,
        edited_due_date=payload.edited_due_date,
        previous_decision_hash=previous.decision_hash if previous else None,
        decision_hash=core._hash(decision_payload),
        decided_at=now,
    )
    db.add(decision)
    db.flush()
    core.write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="REVIEW_RECOVERY_TIMEBAR_EVALUATION",
        entity_type="recovery_timebar_evaluation",
        entity_id=evaluation.id,
        new_values={
            "snapshot_id": str(evaluation.snapshot_id),
            "decision_id": str(decision.id),
            "decision_number": number,
            "action": payload.action,
            "decision_hash": decision.decision_hash,
            "converted_task_id": str(task.id) if task else None,
        },
        details="Human recovery/time-bar disposition recorded separately from immutable source-linked evaluation.",
    )
    db.commit()
    db.refresh(decision)
    return decision


# Patch the preserved implementation at its narrow extension points. Functions
# defined in service_core resolve these module globals at runtime, so all proven
# 12C persistence / hashing / decision behavior remains unchanged except for the
# explicitly hardened human-control and decision-lineage behavior above.
core._marine_recovery_rows = _marine_recovery_rows
core._source_state = _source_state
core._marine_sources = _marine_sources
core.record_decision = _record_decision

# Preserve the service module's established public/private surface for routers,
# tests and downstream integrations while keeping the human-control delta small.
for _name in dir(core):
    if not _name.startswith("__") and _name not in {"_marine_recovery_rows", "_source_state", "_marine_sources"}:
        globals()[_name] = getattr(core, _name)

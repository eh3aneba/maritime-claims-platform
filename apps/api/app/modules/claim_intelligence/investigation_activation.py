from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claim_intelligence.investigation_plan import (
    get_current_investigation_plan,
    plan_source_current,
)
from app.modules.claim_intelligence.models import (
    ClaimInvestigationPlan,
    ClaimInvestigationPlanActivation,
)
from app.modules.claim_intelligence.schemas import ClaimInvestigationPlanActivationWrite
from app.modules.claims.models import Claim
from app.modules.tasks.models import ClaimTask, TaskPriority, TaskSource, TaskStatus, TaskType
from app.modules.users.models import User


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _plan_item_catalog(plan: ClaimInvestigationPlan) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for index, text in enumerate(plan.investigation_tracks):
        items.append({"key": f"track:{index}", "kind": "investigation_track", "text": str(text)})
    for index, text in enumerate(plan.evidence_prompts):
        items.append({"key": f"evidence:{index}", "kind": "evidence_prompt", "text": str(text)})
    for index, text in enumerate(plan.review_topics):
        items.append({"key": f"review:{index}", "kind": "review_topic", "text": str(text)})
    return items


def list_investigation_activations(db: Session, *, claim: Claim) -> list[ClaimInvestigationPlanActivation]:
    return list(
        db.scalars(
            select(ClaimInvestigationPlanActivation)
            .where(
                ClaimInvestigationPlanActivation.organization_id == claim.organization_id,
                ClaimInvestigationPlanActivation.claim_id == claim.id,
            )
            .order_by(ClaimInvestigationPlanActivation.activation_number.desc())
        )
    )


def get_current_investigation_activation(
    db: Session, *, claim: Claim
) -> ClaimInvestigationPlanActivation | None:
    return db.scalar(
        select(ClaimInvestigationPlanActivation)
        .where(
            ClaimInvestigationPlanActivation.organization_id == claim.organization_id,
            ClaimInvestigationPlanActivation.claim_id == claim.id,
        )
        .order_by(ClaimInvestigationPlanActivation.activation_number.desc())
        .limit(1)
    )


def _activation_tasks(
    db: Session, *, claim: Claim, activation: ClaimInvestigationPlanActivation
) -> list[ClaimTask]:
    return list(
        db.scalars(
            select(ClaimTask)
            .where(
                ClaimTask.organization_id == claim.organization_id,
                ClaimTask.claim_id == claim.id,
                ClaimTask.investigation_activation_id == activation.id,
            )
            .order_by(ClaimTask.created_at.asc())
        )
    )


def activation_plan_current(
    db: Session, *, claim: Claim, activation: ClaimInvestigationPlanActivation
) -> bool:
    current = get_current_investigation_plan(db, claim=claim)
    if current is None:
        return False
    return bool(
        current.id == activation.plan_id
        and current.plan_hash == activation.plan_hash
        and plan_source_current(db, claim=claim, plan=current)
    )


def investigation_activation_response(
    db: Session, *, claim: Claim, activation: ClaimInvestigationPlanActivation
) -> dict[str, object]:
    tasks = _activation_tasks(db, claim=claim, activation=activation)
    task_by_key = {task.investigation_item_key: task for task in tasks}
    work_items: list[dict[str, object]] = []
    for item in activation.selected_items:
        task = task_by_key.get(item.get("key"))
        work_items.append(
            {
                "key": item.get("key"),
                "kind": item.get("kind"),
                "text": item.get("text"),
                "task_id": task.id if task else None,
                "task_title": task.title if task else None,
                "task_status": task.status.value if task else None,
                "task_type": task.task_type.value if task else None,
            }
        )
    return {
        "id": activation.id,
        "claim_id": activation.claim_id,
        "activation_number": activation.activation_number,
        "plan_id": activation.plan_id,
        "plan_number": activation.plan_number,
        "plan_hash": activation.plan_hash,
        "selected_items": activation.selected_items,
        "activation_note": activation.activation_note,
        "activated_by_id": activation.activated_by_id,
        "assignee_id": activation.assignee_id,
        "due_date": activation.due_date,
        "previous_activation_hash": activation.previous_activation_hash,
        "activation_key_hash": activation.activation_key_hash,
        "activation_hash": activation.activation_hash,
        "activated_at": activation.activated_at,
        "plan_current": activation_plan_current(db, claim=claim, activation=activation),
        "work_items": work_items,
        "automatic_rule_execution": False,
        "automatic_requirement_activation": False,
        "automatic_document_request": False,
        "automatic_intelligence_build": False,
        "automatic_claim_decision": False,
    }


def _task_shape(item: dict[str, str]) -> tuple[TaskType, str]:
    if item["kind"] == "review_topic":
        return TaskType.REVIEW, "Review — "
    if item["kind"] == "evidence_prompt":
        return TaskType.FOLLOW_UP, "Evidence follow-up — "
    return TaskType.FOLLOW_UP, "Investigate — "


def activate_investigation_plan(
    db: Session,
    *,
    claim: Claim,
    user: User,
    payload: ClaimInvestigationPlanActivationWrite,
) -> ClaimInvestigationPlanActivation:
    if not payload.confirm_activation:
        raise ValueError("Explicit human confirmation is required to activate investigation work items")
    note = payload.note.strip()
    if len(note) < 20:
        raise ValueError("Investigation activation note must contain at least 20 non-whitespace characters")

    locked_claim = db.scalar(
        select(Claim)
        .where(Claim.id == claim.id, Claim.organization_id == user.organization_id)
        .with_for_update()
    )
    if locked_claim is None:
        raise ValueError("Claim is no longer available for investigation activation")

    plan = get_current_investigation_plan(db, claim=locked_claim)
    if plan is None:
        raise ValueError("A current human Investigation Plan is required before activation")
    if payload.plan_id != plan.id or payload.plan_hash != plan.plan_hash:
        raise ValueError("The Investigation Plan changed; refresh the workspace before activation")
    if not plan_source_current(db, claim=locked_claim, plan=plan):
        raise ValueError("The current Investigation Plan has a stale classification/playbook source; adopt a current plan first")

    catalog = _plan_item_catalog(plan)
    by_key = {item["key"]: item for item in catalog}
    requested = set(payload.item_keys)
    unknown = [key for key in payload.item_keys if key not in by_key]
    if unknown:
        raise ValueError("Selected work items must come from the exact immutable Investigation Plan")
    selected = [item for item in catalog if item["key"] in requested]
    if not selected:
        raise ValueError("At least one Investigation Plan item must be selected for activation")

    if payload.assignee_id is not None:
        assignee = db.get(User, payload.assignee_id)
        if assignee is None or assignee.organization_id != locked_claim.organization_id or not assignee.is_active:
            raise ValueError("Assignee must be an active user in the current organization")
    assignee_id = payload.assignee_id or locked_claim.handler_id or user.id

    activation_key_hash = _hash(
        {
            "organization_id": locked_claim.organization_id,
            "claim_id": locked_claim.id,
            "plan_id": plan.id,
            "plan_hash": plan.plan_hash,
            "item_keys": [item["key"] for item in selected],
        }
    )
    existing = db.scalar(
        select(ClaimInvestigationPlanActivation).where(
            ClaimInvestigationPlanActivation.organization_id == locked_claim.organization_id,
            ClaimInvestigationPlanActivation.claim_id == locked_claim.id,
            ClaimInvestigationPlanActivation.activation_key_hash == activation_key_hash,
        )
    )
    if existing is not None:
        return existing

    already_activated = list(
        db.scalars(
            select(ClaimTask).where(
                ClaimTask.organization_id == locked_claim.organization_id,
                ClaimTask.claim_id == locked_claim.id,
                ClaimTask.investigation_plan_id == plan.id,
                ClaimTask.investigation_item_key.in_([item["key"] for item in selected]),
            )
        )
    )
    if already_activated:
        raise ValueError("One or more selected Investigation Plan items have already been activated as human tasks")

    previous = get_current_investigation_activation(db, claim=locked_claim)
    activation_number = previous.activation_number + 1 if previous is not None else 1
    activated_at = datetime.now(UTC)
    previous_hash = previous.activation_hash if previous is not None else None
    activation_payload = {
        "organization_id": locked_claim.organization_id,
        "claim_id": locked_claim.id,
        "activation_number": activation_number,
        "plan_id": plan.id,
        "plan_number": plan.plan_number,
        "plan_hash": plan.plan_hash,
        "selected_items": selected,
        "activation_note": note,
        "activated_by_id": user.id,
        "assignee_id": assignee_id,
        "due_date": payload.due_date,
        "previous_activation_hash": previous_hash,
        "activation_key_hash": activation_key_hash,
        "activated_at": activated_at,
    }
    activation_hash = _hash(activation_payload)
    activation = ClaimInvestigationPlanActivation(**activation_payload, activation_hash=activation_hash)
    db.add(activation)
    db.flush()

    tasks: list[ClaimTask] = []
    for item in selected:
        task_type, prefix = _task_shape(item)
        title = f"{prefix}{item['text']}"[:220]
        task = ClaimTask(
            organization_id=locked_claim.organization_id,
            claim_id=locked_claim.id,
            investigation_plan_id=plan.id,
            investigation_activation_id=activation.id,
            investigation_item_key=item["key"],
            assignee_id=assignee_id,
            title=title,
            description=(
                f"Human-activated from Investigation Plan v{plan.plan_number}. "
                f"Canonical {item['kind'].replace('_', ' ')}: {item['text']}"
            ),
            task_type=task_type,
            status=TaskStatus.OPEN,
            priority=TaskPriority.MEDIUM,
            source=TaskSource.HUMAN,
            due_date=payload.due_date,
        )
        db.add(task)
        db.flush()
        tasks.append(task)

    write_audit_log(
        db,
        organization_id=locked_claim.organization_id,
        user_id=user.id,
        action="ACTIVATE_INVESTIGATION_PLAN_WORK_ITEMS",
        entity_type="claim_investigation_plan_activation",
        entity_id=activation.id,
        new_values={
            "claim_id": str(locked_claim.id),
            "plan_id": str(plan.id),
            "plan_number": plan.plan_number,
            "activation_number": activation_number,
            "work_item_count": len(tasks),
            "task_ids": [str(task.id) for task in tasks],
            "assignee_id": str(assignee_id) if assignee_id else None,
            "due_date": payload.due_date.isoformat() if payload.due_date else None,
        },
        details=(
            "Explicit human activation created bounded human claim tasks from an immutable Investigation Plan. "
            "No rules, requirements, document requests, correspondence, Claim Facts, Claims Intelligence snapshots "
            "or substantive claim decisions were created by this action."
        ),
    )
    db.commit()
    db.refresh(activation)
    return activation

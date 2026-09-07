from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claim_intelligence.domain_playbook import domain_playbook_preview
from app.modules.claim_intelligence.domain_service import get_current_domain_classification
from app.modules.claim_intelligence.models import ClaimInvestigationPlan
from app.modules.claim_intelligence.schemas import ClaimInvestigationPlanWrite
from app.modules.claims.models import Claim
from app.modules.users.models import User


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def list_investigation_plans(db: Session, *, claim: Claim) -> list[ClaimInvestigationPlan]:
    return list(
        db.scalars(
            select(ClaimInvestigationPlan)
            .where(
                ClaimInvestigationPlan.organization_id == claim.organization_id,
                ClaimInvestigationPlan.claim_id == claim.id,
            )
            .order_by(ClaimInvestigationPlan.plan_number.desc())
        )
    )


def get_current_investigation_plan(db: Session, *, claim: Claim) -> ClaimInvestigationPlan | None:
    return db.scalar(
        select(ClaimInvestigationPlan)
        .where(
            ClaimInvestigationPlan.organization_id == claim.organization_id,
            ClaimInvestigationPlan.claim_id == claim.id,
        )
        .order_by(ClaimInvestigationPlan.plan_number.desc())
        .limit(1)
    )


def _canonical_subset(selected: list[str], canonical: list[str], label: str) -> list[str]:
    allowed = set(canonical)
    unknown = [item for item in selected if item not in allowed]
    if unknown:
        raise ValueError(f"Selected {label} must come from the current governed playbook")
    selected_set = set(selected)
    return [item for item in canonical if item in selected_set]


def plan_source_current(db: Session, *, claim: Claim, plan: ClaimInvestigationPlan) -> bool:
    current = get_current_domain_classification(db, claim=claim)
    if current is None:
        return False
    preview = domain_playbook_preview(db, claim=claim)
    return bool(
        current.id == plan.classification_id
        and current.classification_hash == plan.classification_hash
        and preview["registry_version"] == plan.registry_version
        and preview["registry_hash"] == plan.registry_hash
    )


def investigation_plan_response(db: Session, *, claim: Claim, plan: ClaimInvestigationPlan) -> dict[str, object]:
    return {
        "id": plan.id,
        "claim_id": plan.claim_id,
        "plan_number": plan.plan_number,
        "classification_id": plan.classification_id,
        "catalog_version": plan.catalog_version,
        "classification_number": plan.classification_number,
        "classification_hash": plan.classification_hash,
        "registry_version": plan.registry_version,
        "registry_hash": plan.registry_hash,
        "incident_code": plan.incident_code,
        "component_code": plan.component_code,
        "failure_mode": plan.failure_mode,
        "investigation_tracks": plan.investigation_tracks,
        "evidence_prompts": plan.evidence_prompts,
        "review_topics": plan.review_topics,
        "contextual_rule_ids": plan.contextual_rule_ids,
        "adoption_note": plan.adoption_note,
        "adopted_by_id": plan.adopted_by_id,
        "supersedes_plan_id": plan.supersedes_plan_id,
        "previous_plan_hash": plan.previous_plan_hash,
        "adoption_key_hash": plan.adoption_key_hash,
        "plan_hash": plan.plan_hash,
        "adopted_at": plan.adopted_at,
        "source_current": plan_source_current(db, claim=claim, plan=plan),
        "non_authoritative": True,
        "automatic_rule_execution": False,
        "automatic_requirement_activation": False,
        "automatic_task_creation": False,
        "automatic_claim_decision": False,
    }


def adopt_investigation_plan(
    db: Session,
    *,
    claim: Claim,
    user: User,
    payload: ClaimInvestigationPlanWrite,
) -> ClaimInvestigationPlan:
    if not payload.confirm_adoption:
        raise ValueError("Explicit human confirmation is required to adopt an investigation plan")
    note = payload.note.strip()
    if len(note) < 20:
        raise ValueError("Investigation plan note must contain at least 20 non-whitespace characters")

    locked_claim = db.scalar(
        select(Claim)
        .where(Claim.id == claim.id, Claim.organization_id == user.organization_id)
        .with_for_update()
    )
    if locked_claim is None:
        raise ValueError("Claim is no longer available for investigation-plan adoption")

    preview = domain_playbook_preview(db, claim=locked_claim)
    source_ref = preview.get("source_ref")
    playbook = preview.get("playbook")
    context = preview.get("classification_context")
    if preview.get("classification_required") or source_ref is None or playbook is None or context is None:
        raise ValueError("A current human claim-domain classification is required before adopting an investigation plan")

    if payload.registry_version != preview["registry_version"] or payload.registry_hash != preview["registry_hash"]:
        raise ValueError("The governed playbook registry changed; refresh the preview before adopting a plan")
    if str(payload.classification_id) != str(source_ref["id"]) or payload.classification_hash != source_ref["classification_hash"]:
        raise ValueError("The claim-domain classification changed; refresh the preview before adopting a plan")

    tracks = _canonical_subset(
        payload.investigation_tracks,
        list(playbook["investigation_tracks"]),
        "investigation tracks",
    )
    evidence = _canonical_subset(payload.evidence_prompts, list(playbook["evidence_prompts"]), "evidence prompts")
    topics = _canonical_subset(payload.review_topics, list(playbook["review_topics"]), "review topics")
    if not (tracks or evidence or topics):
        raise ValueError("At least one current governed playbook item must be selected")

    adoption_key_hash = _hash(
        {
            "organization_id": locked_claim.organization_id,
            "claim_id": locked_claim.id,
            "classification_id": source_ref["id"],
            "classification_hash": source_ref["classification_hash"],
            "registry_version": preview["registry_version"],
            "registry_hash": preview["registry_hash"],
            "investigation_tracks": tracks,
            "evidence_prompts": evidence,
            "review_topics": topics,
        }
    )
    existing = db.scalar(
        select(ClaimInvestigationPlan).where(
            ClaimInvestigationPlan.organization_id == locked_claim.organization_id,
            ClaimInvestigationPlan.claim_id == locked_claim.id,
            ClaimInvestigationPlan.adoption_key_hash == adoption_key_hash,
        )
    )
    if existing is not None:
        return existing

    previous = get_current_investigation_plan(db, claim=locked_claim)
    plan_number = previous.plan_number + 1 if previous is not None else 1
    adopted_at = datetime.now(UTC)
    previous_hash = previous.plan_hash if previous is not None else None
    plan_payload = {
        "organization_id": locked_claim.organization_id,
        "claim_id": locked_claim.id,
        "plan_number": plan_number,
        "classification_id": source_ref["id"],
        "catalog_version": source_ref["catalog_version"],
        "classification_number": source_ref["classification_number"],
        "classification_hash": source_ref["classification_hash"],
        "registry_version": preview["registry_version"],
        "registry_hash": preview["registry_hash"],
        "incident_code": context["incident_code"],
        "component_code": context["component_code"],
        "failure_mode": context["failure_mode"],
        "investigation_tracks": tracks,
        "evidence_prompts": evidence,
        "review_topics": topics,
        "contextual_rule_ids": list(playbook["contextual_rule_ids"]),
        "adoption_note": note,
        "adopted_by_id": user.id,
        "supersedes_plan_id": previous.id if previous is not None else None,
        "previous_plan_hash": previous_hash,
        "adoption_key_hash": adoption_key_hash,
        "adopted_at": adopted_at,
    }
    plan_hash = _hash(plan_payload)
    row = ClaimInvestigationPlan(**plan_payload, plan_hash=plan_hash)
    db.add(row)
    db.flush()

    write_audit_log(
        db,
        organization_id=locked_claim.organization_id,
        user_id=user.id,
        action="ADOPT_CLAIM_INVESTIGATION_PLAN",
        entity_type="claim_investigation_plan",
        entity_id=row.id,
        new_values={
            "claim_id": str(locked_claim.id),
            "plan_number": plan_number,
            "incident_code": context["incident_code"],
            "classification_number": source_ref["classification_number"],
            "registry_version": preview["registry_version"],
            "investigation_track_count": len(tracks),
            "evidence_prompt_count": len(evidence),
            "review_topic_count": len(topics),
            "contextual_rule_reference_count": len(playbook["contextual_rule_ids"]),
            "supersedes_prior_plan": previous is not None,
        },
        details=(
            "Human-adopted investigation plan recorded from the exact governed playbook preview. Free-text note and "
            "integrity hashes are excluded from audit metadata. Adoption does not execute rules, activate evidence "
            "requirements, create tasks, build Claims Intelligence or make a substantive claim decision."
        ),
    )
    db.commit()
    db.refresh(row)
    return row

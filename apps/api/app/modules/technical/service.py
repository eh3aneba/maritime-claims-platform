from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.intelligence.models import AISemanticKind, AIReviewStatus, DocumentExtraction
from app.modules.rules.models import ClaimIssue, IssueCategory
from app.modules.technical.models import TECHNICAL_DECISION_ACTIONS, TechnicalInvestigationDecision


REVIEWED = {AIReviewStatus.APPROVED, AIReviewStatus.EDITED}


class TechnicalTopicNotFoundError(ValueError):
    pass


class TechnicalDecisionConflictError(ValueError):
    pass


def _reviewed_extractions(db: Session, *, claim_id: UUID, organization_id: UUID, prefix: str) -> list[DocumentExtraction]:
    return list(db.scalars(select(DocumentExtraction).where(
        DocumentExtraction.claim_id == claim_id,
        DocumentExtraction.organization_id == organization_id,
        DocumentExtraction.human_status.in_(REVIEWED),
        DocumentExtraction.field_path.like(f"{prefix}%"),
    ).order_by(DocumentExtraction.field_path.asc())))


def _value(ex: DocumentExtraction) -> Any:
    return ex.approved_value if ex.human_status == AIReviewStatus.EDITED else (ex.normalized_value if ex.normalized_value is not None else ex.raw_value)


def _evidence(ex: DocumentExtraction) -> dict[str, Any]:
    return {
        "extraction_id": ex.id,
        "field_path": ex.field_path,
        "value": _value(ex),
        "document_id": ex.document_id,
        "source_quote": ex.source_quote,
        "source_locator_type": ex.source_locator_type,
        "source_locator_value": ex.source_locator_value,
        "source_verified": ex.source_verified,
    }


def _follow_up_for_opinion(text: str) -> tuple[list[str], list[str]]:
    lowered = text.lower()
    missing: list[str] = []
    follow: list[str] = []
    if any(word in lowered for word in ("lubric", "oil starvation", "low oil")):
        missing += ["Lubricating-oil analysis / condition evidence", "Relevant lube-oil alarms, filters and pump records"]
        follow += ["Review lube-oil analysis, filter inspection, pump condition and alarm history."]
    if "bearing" in lowered:
        missing += ["Bearing measurements / clearances", "Bearing condition photographs or inspection records"]
        follow += ["Obtain bearing measurements, clearances and workshop photographs."]
    if any(word in lowered for word in ("foreign object", "fod", "foreign material")):
        missing += ["Foreign-object inspection evidence", "Compressor/turbine blade photographs"]
        follow += ["Review physical evidence supporting foreign-object ingress and damage path."]
    if any(word in lowered for word in ("assembly", "workmanship", "incorrect fitting")):
        missing += ["Previous overhaul scope and assembly records", "Post-overhaul clearances / commissioning results"]
        follow += ["Review previous overhaul workmanship, assembly records and post-overhaul testing."]
    if not missing:
        missing.append("Independent technical evidence supporting or contradicting the source opinion")
        follow.append("Test the workshop opinion against logs, maintenance history, measurements and survey evidence.")
    return missing, follow


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value") and isinstance(getattr(value, "value"), (str, int, float, bool)):
        return value.value
    return value


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _topic_fingerprint(row: dict[str, Any]) -> str:
    return _canonical_hash({
        "key": row["key"],
        "topic_kind": row["topic_kind"],
        "title": row["title"],
        "severity": row["severity"],
        "status": row["status"],
        "evidence_for": row["evidence_for"],
        "evidence_against": row["evidence_against"],
        "unknown_or_missing": row["unknown_or_missing"],
        "recommended_follow_up": row["recommended_follow_up"],
        "explanation": row["explanation"],
    })


def _decision_payload(decision: TechnicalInvestigationDecision) -> dict[str, Any]:
    return {
        "id": decision.id,
        "topic_key": decision.topic_key,
        "topic_kind": decision.topic_kind,
        "state_fingerprint": decision.state_fingerprint,
        "state_version": decision.state_version,
        "decision_number": decision.decision_number,
        "action": decision.action,
        "note": decision.note,
        "decided_by_id": decision.decided_by_id,
        "decided_at": decision.decided_at,
        "previous_decision_hash": decision.previous_decision_hash,
        "decision_hash": decision.decision_hash,
    }


def _decision_hash(
    *,
    organization_id: UUID,
    claim_id: UUID,
    topic_key: str,
    topic_kind: str,
    state_fingerprint: str,
    state_version: int,
    decision_number: int,
    action: str,
    note: str,
    decided_by_id: UUID | None,
    previous_decision_hash: str | None,
) -> str:
    return _canonical_hash({
        "organization_id": organization_id,
        "claim_id": claim_id,
        "topic_key": topic_key,
        "topic_kind": topic_kind,
        "state_fingerprint": state_fingerprint,
        "state_version": state_version,
        "decision_number": decision_number,
        "action": action,
        "note": note,
        "decided_by_id": decided_by_id,
        "previous_decision_hash": previous_decision_hash,
    })


def _decision_history(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
    topic_key: str | None = None,
) -> list[TechnicalInvestigationDecision]:
    stmt = select(TechnicalInvestigationDecision).where(
        TechnicalInvestigationDecision.claim_id == claim_id,
        TechnicalInvestigationDecision.organization_id == organization_id,
    )
    if topic_key is not None:
        stmt = stmt.where(TechnicalInvestigationDecision.topic_key == topic_key)
    stmt = stmt.order_by(TechnicalInvestigationDecision.topic_key.asc(), TechnicalInvestigationDecision.decision_number.asc())
    return list(db.scalars(stmt))


def _build_raw_review(db: Session, *, claim_id: UUID, organization_id: UUID) -> dict[str, Any]:
    facts = list(db.scalars(select(ClaimFact).where(ClaimFact.claim_id == claim_id, ClaimFact.organization_id == organization_id)))
    fact_map = {fact.field_path: fact.value for fact in facts}
    maintenance = {k: v for k, v in fact_map.items() if k.startswith("maintenance.") or k in {"repair.temporary", "workshop.repairable"}}

    workshop_findings = _reviewed_extractions(db, claim_id=claim_id, organization_id=organization_id, prefix="workshop.damage_findings[")
    repair_options = _reviewed_extractions(db, claim_id=claim_id, organization_id=organization_id, prefix="workshop.repair_options[")
    cause_opinions = [ex for ex in _reviewed_extractions(db, claim_id=claim_id, organization_id=organization_id, prefix="workshop.suspected_cause_opinions[") if ex.semantic_kind == AISemanticKind.OPINION]
    issues = list(db.scalars(select(ClaimIssue).where(
        ClaimIssue.claim_id == claim_id,
        ClaimIssue.organization_id == organization_id,
        ClaimIssue.category == IssueCategory.TECHNICAL,
        ClaimIssue.is_active.is_(True),
    ).order_by(ClaimIssue.severity.desc(), ClaimIssue.title.asc())))

    matrix: list[dict[str, Any]] = []
    for issue in issues:
        unknown: list[str] = []
        against: list[Any] = []
        follow: list[str] = []
        if issue.rule_id == "TECH-001":
            if fact_map.get("maintenance.interval_extension_approved") is True:
                against.append({"interval_extension_approved": True, "details": fact_map.get("maintenance.interval_extension_details")})
                follow.append("Verify the maker/authorized extension scope and effective interval before drawing any maintenance conclusion.")
            else:
                unknown.append("Maker-approved interval extension has not been established.")
                follow.append("Request any maker/authorized extension approval and the applicable revised interval.")
        elif issue.rule_id == "TECH-002":
            unknown += ["Previous overhaul scope", "Assembly/workmanship evidence", "Post-overhaul testing and clearances"]
            follow.append("Review the previous overhaul report, replaced/reused parts, assembly records and commissioning results.")
        elif issue.rule_id == "TECH-003":
            unknown += ["Technical justification for deferral", "Deferral approval / risk assessment", "Whether deferred task is technically related to damaged component"]
            follow.append("Obtain the PMS deferral basis, approval and any risk assessment before assessing relevance.")
        elif issue.rule_id == "TECH-006":
            unknown += ["Class conditions / expiry", "Permanent repair scope and completion plan"]
            follow.append("Confirm Class approval conditions and permanent repair requirement.")
        matrix.append({
            "key": issue.issue_key,
            "topic_kind": "rule_issue",
            "title": issue.title,
            "severity": issue.severity.value,
            "status": issue.status.value,
            "evidence_for": [issue.evidence] if issue.evidence else [],
            "evidence_against": against,
            "unknown_or_missing": unknown,
            "recommended_follow_up": follow,
            "explanation": issue.explanation or issue.description,
        })

    for opinion in cause_opinions:
        text = str(_value(opinion) or "")
        missing, follow = _follow_up_for_opinion(text)
        matrix.append({
            "key": f"workshop_opinion_{opinion.id}",
            "topic_kind": "workshop_opinion",
            "title": f"Workshop cause opinion: {text[:100]}",
            "severity": "medium",
            "status": "under_review",
            "evidence_for": [_evidence(opinion)],
            "evidence_against": [],
            "unknown_or_missing": missing,
            "recommended_follow_up": follow,
            "explanation": "This is a human-reviewed source opinion, not a confirmed cause. It must be tested against independent technical evidence.",
        })

    return {
        "maintenance_facts": maintenance,
        "workshop_findings": [_evidence(ex) for ex in workshop_findings],
        "workshop_repair_options": [_evidence(ex) for ex in repair_options],
        "workshop_cause_opinions": [_evidence(ex) for ex in cause_opinions],
        "matrix": matrix,
        "generated_at": datetime.now(UTC),
    }


def _enrich_with_decisions(
    review: dict[str, Any],
    *,
    history: list[TechnicalInvestigationDecision],
) -> dict[str, Any]:
    latest: dict[str, TechnicalInvestigationDecision] = {}
    for decision in history:
        latest[decision.topic_key] = decision

    for row in review["matrix"]:
        fingerprint = _topic_fingerprint(row)
        prior = latest.get(row["key"])
        if prior is None:
            state_version = 1
            decision_state = "none"
        elif prior.state_fingerprint == fingerprint:
            state_version = prior.state_version
            decision_state = "current"
        else:
            state_version = prior.state_version + 1
            decision_state = "stale"
        row["state_fingerprint"] = fingerprint
        row["state_version"] = state_version
        row["decision_state"] = decision_state
        row["latest_decision"] = _decision_payload(prior) if prior is not None else None
    return review


def build_technical_review(db: Session, *, claim_id: UUID, organization_id: UUID) -> dict[str, Any]:
    review = _build_raw_review(db, claim_id=claim_id, organization_id=organization_id)
    return _enrich_with_decisions(
        review,
        history=_decision_history(db, claim_id=claim_id, organization_id=organization_id),
    )


def technical_decision_history(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
    topic_key: str,
) -> dict[str, Any]:
    history = _decision_history(
        db,
        claim_id=claim_id,
        organization_id=organization_id,
        topic_key=topic_key,
    )
    review = build_technical_review(db, claim_id=claim_id, organization_id=organization_id)
    current = next((row for row in review["matrix"] if row["key"] == topic_key), None)
    if current is None and not history:
        raise TechnicalTopicNotFoundError("Technical investigation topic not found")
    latest = history[-1] if history else None
    if current is None:
        decision_state = "stale" if latest is not None else "none"
        current_fingerprint = None
        current_version = None
    else:
        decision_state = current["decision_state"]
        current_fingerprint = current["state_fingerprint"]
        current_version = current["state_version"]
    return {
        "topic_key": topic_key,
        "current_state_fingerprint": current_fingerprint,
        "current_state_version": current_version,
        "decision_state": decision_state,
        "items": [_decision_payload(item) for item in history],
    }


def record_technical_decision(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
    topic_key: str,
    action: str,
    note: str,
    expected_state_fingerprint: str,
    expected_state_version: int,
    confirm_re_review: bool,
    decided_by_id: UUID | None,
) -> TechnicalInvestigationDecision:
    if action not in TECHNICAL_DECISION_ACTIONS:
        raise TechnicalDecisionConflictError("Unsupported technical review action")

    claim = db.scalar(select(Claim).where(
        Claim.id == claim_id,
        Claim.organization_id == organization_id,
    ).with_for_update())
    if claim is None:
        raise TechnicalTopicNotFoundError("Claim not found")

    review = build_technical_review(db, claim_id=claim_id, organization_id=organization_id)
    current = next((row for row in review["matrix"] if row["key"] == topic_key), None)
    if current is None:
        raise TechnicalTopicNotFoundError("Technical investigation topic not found")
    if (
        current["state_fingerprint"] != expected_state_fingerprint
        or current["state_version"] != expected_state_version
    ):
        raise TechnicalDecisionConflictError(
            "Technical evidence changed. Refresh the current topic before recording a decision."
        )

    history = _decision_history(
        db,
        claim_id=claim_id,
        organization_id=organization_id,
        topic_key=topic_key,
    )
    latest = history[-1] if history else None
    clean_note = note.strip()

    if (
        latest is not None
        and latest.state_fingerprint == current["state_fingerprint"]
        and latest.state_version == current["state_version"]
        and latest.action == action
        and latest.note == clean_note
        and latest.decided_by_id == decided_by_id
    ):
        return latest

    if latest is not None and not confirm_re_review:
        raise TechnicalDecisionConflictError(
            "A prior human technical disposition exists. Explicit re-review is required before changing or refreshing it."
        )

    decision_number = (latest.decision_number + 1) if latest is not None else 1
    previous_hash = latest.decision_hash if latest is not None else None
    decided_at = datetime.now(UTC)
    decision_hash = _decision_hash(
        organization_id=organization_id,
        claim_id=claim_id,
        topic_key=topic_key,
        topic_kind=current["topic_kind"],
        state_fingerprint=current["state_fingerprint"],
        state_version=current["state_version"],
        decision_number=decision_number,
        action=action,
        note=clean_note,
        decided_by_id=decided_by_id,
        previous_decision_hash=previous_hash,
    )
    decision = TechnicalInvestigationDecision(
        organization_id=organization_id,
        claim_id=claim_id,
        topic_key=topic_key,
        topic_kind=current["topic_kind"],
        state_fingerprint=current["state_fingerprint"],
        state_version=current["state_version"],
        decision_number=decision_number,
        action=action,
        note=clean_note,
        decided_by_id=decided_by_id,
        decided_at=decided_at,
        previous_decision_hash=previous_hash,
        decision_hash=decision_hash,
    )
    db.add(decision)
    db.flush()
    return decision
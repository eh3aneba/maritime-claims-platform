from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.claim_intelligence import service_core as core
from app.modules.claim_intelligence.domain_catalog import INCIDENT_DOMAINS, MACHINERY_COMPONENTS
from app.modules.claim_intelligence.models import (
    ClaimDomainClassification,
    ClaimIntelligenceItem,
    ClaimIntelligenceSnapshot,
)
from app.modules.recovery_timebar.models import RecoveryTimebarEvaluation
from app.modules.recovery_timebar.service import (
    ENGINE_VERSION as RECOVERY_TIMEBAR_ENGINE_VERSION,
    build_recovery_timebar,
)

# Preserve the established Phase 12A service surface while layering structured
# Phase 12C recovery/time-bar output without creating an intermediate 12A
# intelligence snapshot.
for _name in dir(core):
    if not _name.startswith("__") and _name != "build_claim_intelligence":
        globals()[_name] = getattr(core, _name)

ENGINE_VERSION = "12C-CI.1"
DOMAIN_CONTEXT_INTEGRATION_VERSION = "16.1-B.1"

_INCIDENT_TITLE_BY_CODE = {str(row["code"]): str(row["title"]) for row in INCIDENT_DOMAINS}
_COMPONENT_TITLE_BY_CODE = {str(row["code"]): str(row["title"]) for row in MACHINERY_COMPONENTS}


def _structured_source_state(snapshot: Any, rows: list[RecoveryTimebarEvaluation]) -> dict:
    return {
        "snapshot_id": str(snapshot.id),
        "snapshot_version": snapshot.snapshot_version,
        "engine_version": snapshot.engine_version,
        "source_state_hash": snapshot.source_state_hash,
        "snapshot_hash": snapshot.snapshot_hash,
        "evaluations": [
            {
                "id": str(row.id),
                "kind": row.kind,
                "status": row.status,
                "urgency": row.urgency,
                "candidate_deadline": row.candidate_deadline.isoformat() if row.candidate_deadline else None,
                "evaluation_hash": row.evaluation_hash,
            }
            for row in rows
        ],
    }


def _structured_recovery_timebar_items(rows: list[RecoveryTimebarEvaluation]) -> list[dict]:
    output: list[dict] = []
    for row in rows:
        if row.status not in {"triggered", "insufficient_evidence"}:
            continue
        category = "recovery_lead" if row.kind == "recovery" else "deadline_lead"
        severity = row.urgency if row.urgency in core._SEVERITY_SCORE else "medium"
        description_parts = [row.candidate_implication]
        if row.candidate_deadline is not None:
            description_parts.append(
                f"Candidate date: {row.candidate_deadline.isoformat()} — human/legal verification required before reliance."
            )
        if row.missing_prerequisites:
            description_parts.append("Missing prerequisites: " + "; ".join(str(value) for value in row.missing_prerequisites))
        description_parts.append("Review and act, if appropriate, in the Recovery & Time-bar workspace.")
        sources = [
            core._source(
                "recovery_timebar_evaluation",
                row.id,
                snapshot_id=row.snapshot_id,
                evaluation_kind=row.kind,
                status=row.status,
                urgency=row.urgency,
                evaluation_hash=row.evaluation_hash,
                candidate_deadline=row.candidate_deadline.isoformat() if row.candidate_deadline else None,
            )
        ]
        sources.extend(list(row.source_refs or []))
        output.append(
            core._item(
                key=f"recovery-timebar-{row.kind}-{row.id}",
                category=category,
                title=row.title,
                description=" ".join(description_parts),
                severity=severity,
                urgency=core._SEVERITY_SCORE[severity],
                evidence=100,
                rationale=(
                    "Structured Phase 12C Recovery & Time-bar evaluation. This Claims Intelligence item is a read-only proxy; "
                    "the source evaluation remains non-authoritative and any task/diary conversion requires explicit human "
                    "review in the Recovery & Time-bar workspace. " + row.rationale
                ),
                sources=sources,
                action_type=None,
                suggested_action=None,
                related_entity_type="recovery_timebar_evaluation",
                related_entity_id=row.id,
            )
        )
    return output


def _latest_rows(db: Session, snapshot_id) -> list[RecoveryTimebarEvaluation]:
    return list(
        db.scalars(
            select(RecoveryTimebarEvaluation)
            .where(RecoveryTimebarEvaluation.snapshot_id == snapshot_id)
            .order_by(RecoveryTimebarEvaluation.kind.asc(), RecoveryTimebarEvaluation.evaluation_key.asc())
        )
    )


def _current_domain_classification(db: Session, *, claim) -> ClaimDomainClassification | None:
    return db.scalar(
        select(ClaimDomainClassification)
        .where(
            ClaimDomainClassification.organization_id == claim.organization_id,
            ClaimDomainClassification.claim_id == claim.id,
        )
        .order_by(ClaimDomainClassification.classification_number.desc())
        .limit(1)
    )


def _domain_context_state(row: ClaimDomainClassification | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "catalog_version": row.catalog_version,
        "classification_number": row.classification_number,
        "incident_code": row.incident_code,
        "component_code": row.component_code,
        "failure_mode": row.failure_mode,
        "classification_hash": row.classification_hash,
    }


def _domain_context_item(row: ClaimDomainClassification) -> dict:
    incident_title = _INCIDENT_TITLE_BY_CODE.get(row.incident_code, row.incident_code.replace("_", " ").title())
    component_title = (
        _COMPONENT_TITLE_BY_CODE.get(row.component_code, row.component_code.replace("_", " ").title())
        if row.component_code
        else None
    )
    context_parts = [incident_title]
    if component_title:
        context_parts.append(component_title)
    if row.failure_mode:
        context_parts.append(row.failure_mode)

    return core._item(
        key=f"domain-classification-{row.id}",
        category="domain_context",
        title=f"Claim domain: {incident_title}",
        description="Human-confirmed domain context: " + " — ".join(context_parts) + ".",
        severity="info",
        urgency=25,
        evidence=100,
        rationale=(
            "Copied from the current human-confirmed ClaimDomainClassification lineage. This is bounded incident context only; "
            "it does not determine causation, coverage, fault, liability, recoverability or any other substantive claim outcome."
        ),
        sources=[
            core._source(
                "claim_domain_classification",
                row.id,
                catalog_version=row.catalog_version,
                classification_number=row.classification_number,
                classification_hash=row.classification_hash,
            )
        ],
        action_type=None,
        suggested_action=None,
        related_entity_type="claim_domain_classification",
        related_entity_id=row.id,
    )


def _base_payload(db: Session, *, claim, user) -> tuple[str, list[dict], dict]:
    """Build the deterministic base payload without persisting a snapshot.

    The current human-confirmed claim-domain classification is consumed only
    here, after an operator explicitly requests an Intelligence build. It is
    source-linked context and is deliberately not passed into rule evaluation.
    """
    core.evaluate_claim_rules(db, claim=claim, user=user, trigger="claims_intelligence")
    core.build_chronology(db, claim=claim, user=user)
    policy = core.build_policy_intelligence(
        db,
        claim_id=claim.id,
        organization_id=claim.organization_id,
    )
    data = core._load_sources(db, claim)
    core_state = core._source_state(claim, data, policy)
    domain_classification = _current_domain_classification(db, claim=claim)
    domain_state = _domain_context_state(domain_classification)
    state_hash = core._hash(
        {
            "phase12a_source_state": core_state,
            "claim_domain_context": domain_state,
            "domain_context_integration_version": DOMAIN_CONTEXT_INTEGRATION_VERSION,
        }
    )
    item_payloads = core._build_items(claim, data, policy)
    if domain_classification is not None:
        item_payloads.append(_domain_context_item(domain_classification))
        item_payloads.sort(key=lambda row: (-row["rank_score"], row["category"], row["item_key"]))

    counts: dict[str, int] = {}
    for row in item_payloads:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    summary = {
        "source_linked": True,
        "non_authoritative": True,
        "human_review_required": True,
        "external_provider_scope_expanded": False,
        "ruleset_version": core.RULESET_VERSION,
        "chronology_build_version": core.CHRONOLOGY_BUILD_VERSION,
        "domain_context_integration_version": DOMAIN_CONTEXT_INTEGRATION_VERSION,
        "domain_classification_present": domain_classification is not None,
        "domain_context_count": counts.get("domain_context", 0),
        "domain_classification_drives_rules": False,
        "item_count": len(item_payloads),
        "category_counts": counts,
        "missing_evidence_count": counts.get("missing_evidence", 0),
        "open_conflict_count": counts.get("conflict", 0),
        "hypothesis_count": counts.get("hypothesis", 0),
        "financial_recovery_lead_count": counts.get("financial_lead", 0) + counts.get("recovery_lead", 0),
        "deadline_lead_count": counts.get("deadline_lead", 0),
        "next_action_count": counts.get("next_action", 0),
        "authoritative_claim_facts_updated": False,
        "coverage_decision_made": False,
        "causation_decision_made": False,
        "liability_decision_made": False,
        "reserve_or_settlement_decision_made": False,
    }
    return state_hash, item_payloads, summary


def build_claim_intelligence(db: Session, *, claim, user) -> ClaimIntelligenceSnapshot:
    recovery_snapshot = build_recovery_timebar(db, claim=claim, user=user)
    recovery_timebar_rows = _latest_rows(db, recovery_snapshot.id)

    base_state_hash, item_payloads, summary = _base_payload(db, claim=claim, user=user)

    # Structured Phase 12C proxies replace only the legacy heuristic recovery
    # pair. Independent policy issue flags remain intact.
    legacy_keys = {"recovery-preservation-lead", "next-recovery-preservation"}
    item_payloads = [row for row in item_payloads if row["item_key"] not in legacy_keys]
    item_payloads.extend(_structured_recovery_timebar_items(recovery_timebar_rows))
    item_payloads.sort(key=lambda row: (-row["rank_score"], row["category"], row["item_key"]))

    structured_state = _structured_source_state(recovery_snapshot, recovery_timebar_rows)
    combined_source_state_hash = core._hash(
        {
            "phase12a_source_state_hash": base_state_hash,
            "recovery_timebar": structured_state,
            "integration_version": ENGINE_VERSION,
            "domain_context_integration_version": DOMAIN_CONTEXT_INTEGRATION_VERSION,
        }
    )
    existing = db.scalar(
        select(ClaimIntelligenceSnapshot).where(
            ClaimIntelligenceSnapshot.organization_id == claim.organization_id,
            ClaimIntelligenceSnapshot.claim_id == claim.id,
            ClaimIntelligenceSnapshot.source_state_hash == combined_source_state_hash,
        )
    )
    if existing is not None:
        return existing

    counts: dict[str, int] = {}
    for row in item_payloads:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    summary.update(
        {
            "phase12c_integration_version": ENGINE_VERSION,
            "recovery_timebar_engine_version": RECOVERY_TIMEBAR_ENGINE_VERSION,
            "recovery_timebar_snapshot_id": str(recovery_snapshot.id),
            "recovery_timebar_snapshot_hash": recovery_snapshot.snapshot_hash,
            "structured_recovery_timebar_count": sum(
                1 for row in recovery_timebar_rows if row.status in {"triggered", "insufficient_evidence"}
            ),
            "item_count": len(item_payloads),
            "category_counts": counts,
            "domain_context_count": counts.get("domain_context", 0),
            "missing_evidence_count": counts.get("missing_evidence", 0),
            "open_conflict_count": counts.get("conflict", 0),
            "hypothesis_count": counts.get("hypothesis", 0),
            "financial_recovery_lead_count": counts.get("financial_lead", 0) + counts.get("recovery_lead", 0),
            "deadline_lead_count": counts.get("deadline_lead", 0),
            "next_action_count": counts.get("next_action", 0),
            "recoverability_decision_made": False,
            "authoritative_deadline_created": False,
        }
    )
    snapshot_hash = core._hash(
        {
            "engine": ENGINE_VERSION,
            "domain_context_integration_version": DOMAIN_CONTEXT_INTEGRATION_VERSION,
            "source_state_hash": combined_source_state_hash,
            "summary": summary,
            "item_hashes": [row["item_hash"] for row in item_payloads],
        }
    )
    current_max = db.scalar(
        select(func.max(ClaimIntelligenceSnapshot.snapshot_version)).where(
            ClaimIntelligenceSnapshot.organization_id == claim.organization_id,
            ClaimIntelligenceSnapshot.claim_id == claim.id,
        )
    ) or 0
    now = datetime.now(UTC)
    snapshot = ClaimIntelligenceSnapshot(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        generated_by_id=user.id,
        snapshot_version=current_max + 1,
        # Keep the established Claims Intelligence contract version at 12A.1;
        # the structured 12C and 16.1-B context layers are independently
        # versioned in summary/source hashes.
        engine_version=core.ENGINE_VERSION,
        source_state_hash=combined_source_state_hash,
        snapshot_hash=snapshot_hash,
        summary=summary,
        generated_at=now,
    )
    db.add(snapshot)
    db.flush()
    for payload in item_payloads:
        db.add(
            ClaimIntelligenceItem(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                snapshot_id=snapshot.id,
                **payload,
            )
        )
    core.write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="BUILD_CLAIM_INTELLIGENCE",
        entity_type="claim",
        entity_id=claim.id,
        new_values={
            "snapshot_id": str(snapshot.id),
            "snapshot_version": snapshot.snapshot_version,
            "source_state_hash": combined_source_state_hash,
            "snapshot_hash": snapshot_hash,
            "recovery_timebar_snapshot_id": str(recovery_snapshot.id),
            "recovery_timebar_snapshot_hash": recovery_snapshot.snapshot_hash,
            **summary,
        },
        details=(
            "Built one immutable Claims Intelligence snapshot with structured, non-authoritative Phase 12C recovery/time-bar "
            "evaluations and optional human-confirmed Phase 16.1-B domain context. Domain classification does not drive rules "
            "or substantive claim decisions."
        ),
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot

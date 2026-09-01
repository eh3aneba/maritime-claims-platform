from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.claim_intelligence import service_core as core
from app.modules.claim_intelligence.models import ClaimIntelligenceItem, ClaimIntelligenceSnapshot
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


def _base_payload(db: Session, *, claim, user) -> tuple[str, list[dict], dict]:
    """Build the Phase 12A deterministic payload without persisting a snapshot.

    Phase 12C must not create an observable intermediate Claims Intelligence
    snapshot. We therefore reuse the proven 12A prerequisite layers and private
    payload builders, then persist exactly one combined immutable snapshot below.
    """
    core.evaluate_claim_rules(db, claim=claim, user=user, trigger="claims_intelligence")
    core.build_chronology(db, claim=claim, user=user)
    policy = core.build_policy_intelligence(
        db,
        claim_id=claim.id,
        organization_id=claim.organization_id,
    )
    data = core._load_sources(db, claim)
    state = core._source_state(claim, data, policy)
    state_hash = core._hash(state)
    item_payloads = core._build_items(claim, data, policy)

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
        # the structured 12C layer is independently versioned in summary/hash.
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
            "evaluations. Recovery/time-bar proxy items are read-only and preserve human-controlled task/diary conversion."
        ),
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot

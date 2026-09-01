from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.chronology.service import BUILD_VERSION as CHRONOLOGY_BUILD_VERSION, build_chronology
from app.modules.claim_intelligence import service_core as core
from app.modules.claim_intelligence.models import ClaimIntelligenceItem, ClaimIntelligenceSnapshot
from app.modules.claims.models import Claim
from app.modules.policy_intelligence.service import build_policy_intelligence
from app.modules.recovery_timebar.models import RecoveryTimebarEvaluation
from app.modules.recovery_timebar.service import ENGINE_VERSION as RECOVERY_TIMEBAR_ENGINE_VERSION, build_recovery_timebar
from app.modules.rules.library import RULESET_VERSION
from app.modules.rules.service import evaluate_claim_rules
from app.modules.users.models import User

ENGINE_VERSION = core.ENGINE_VERSION
DISCLAIMER = core.DISCLAIMER
LEGACY_RECOVERY_ITEM_KEYS = {"recovery-preservation-lead", "next-recovery-preservation"}

# Public response/review behavior remains the proven Phase 12A core implementation.
dashboard_response = core.dashboard_response
latest_snapshot = core.latest_snapshot
record_item_decision = core.record_item_decision
snapshot_response = core.snapshot_response


def _recovery_timebar_rows(db: Session, snapshot_id) -> list[RecoveryTimebarEvaluation]:
    return list(
        db.scalars(
            select(RecoveryTimebarEvaluation)
            .where(RecoveryTimebarEvaluation.snapshot_id == snapshot_id)
            .order_by(RecoveryTimebarEvaluation.kind.asc(), RecoveryTimebarEvaluation.evaluation_key.asc())
        )
    )


def _recovery_timebar_state(snapshot, rows: list[RecoveryTimebarEvaluation]) -> dict[str, Any]:
    return {
        "snapshot_id": str(snapshot.id),
        "snapshot_version": snapshot.snapshot_version,
        "snapshot_hash": snapshot.snapshot_hash,
        "source_state_hash": snapshot.source_state_hash,
        "engine_version": snapshot.engine_version,
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
                kind=row.kind,
                status=row.status,
                urgency=row.urgency,
                evaluation_hash=row.evaluation_hash,
                candidate_deadline=row.candidate_deadline,
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


def build_claim_intelligence(db: Session, *, claim: Claim, user: User) -> ClaimIntelligenceSnapshot:
    # Keep deterministic prerequisite layers current. They consume only controlled / human-reviewed evidence.
    evaluate_claim_rules(db, claim=claim, user=user, trigger="claims_intelligence")
    build_chronology(db, claim=claim, user=user)
    policy = build_policy_intelligence(db, claim_id=claim.id, organization_id=claim.organization_id)

    # Phase 12C is first-class input to Claims Intelligence. It never invents a deadline when source prerequisites are absent.
    recovery_timebar_snapshot = build_recovery_timebar(db, claim=claim, user=user)
    recovery_timebar_rows = _recovery_timebar_rows(db, recovery_timebar_snapshot.id)

    data = core._load_sources(db, claim)
    state = core._source_state(claim, data, policy)
    state["recovery_timebar"] = _recovery_timebar_state(recovery_timebar_snapshot, recovery_timebar_rows)
    state.setdefault("engine", {})["recovery_timebar"] = RECOVERY_TIMEBAR_ENGINE_VERSION
    state_hash = core._hash(state)

    existing = db.scalar(
        select(ClaimIntelligenceSnapshot).where(
            ClaimIntelligenceSnapshot.organization_id == claim.organization_id,
            ClaimIntelligenceSnapshot.claim_id == claim.id,
            ClaimIntelligenceSnapshot.source_state_hash == state_hash,
        )
    )
    if existing is not None:
        return existing

    # Preserve the proven Phase 12A item builder, remove its legacy heuristic recovery proxy, then add structured 12C proxies.
    item_payloads = [
        row
        for row in core._build_items(claim, data, policy)
        if row["item_key"] not in LEGACY_RECOVERY_ITEM_KEYS
    ]
    item_payloads.extend(_structured_recovery_timebar_items(recovery_timebar_rows))
    item_payloads = sorted(
        {row["item_key"]: row for row in item_payloads}.values(),
        key=lambda row: (-row["rank_score"], row["category"], row["item_key"]),
    )

    counts: dict[str, int] = {}
    for row in item_payloads:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    summary = {
        "source_linked": True,
        "non_authoritative": True,
        "human_review_required": True,
        "external_provider_scope_expanded": False,
        "ruleset_version": RULESET_VERSION,
        "chronology_build_version": CHRONOLOGY_BUILD_VERSION,
        "recovery_timebar_engine_version": RECOVERY_TIMEBAR_ENGINE_VERSION,
        "recovery_timebar_snapshot_id": str(recovery_timebar_snapshot.id),
        "recovery_timebar_snapshot_hash": recovery_timebar_snapshot.snapshot_hash,
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
        "authoritative_claim_facts_updated": False,
        "authoritative_deadline_created": False,
        "coverage_decision_made": False,
        "causation_decision_made": False,
        "liability_decision_made": False,
        "recoverability_decision_made": False,
        "reserve_or_settlement_decision_made": False,
    }
    item_hashes = [row["item_hash"] for row in item_payloads]
    snapshot_hash = core._hash(
        {
            "engine": ENGINE_VERSION,
            "source_state_hash": state_hash,
            "summary": summary,
            "item_hashes": item_hashes,
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
        engine_version=ENGINE_VERSION,
        source_state_hash=state_hash,
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
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="BUILD_CLAIM_INTELLIGENCE",
        entity_type="claim",
        entity_id=claim.id,
        new_values={
            "snapshot_id": str(snapshot.id),
            "snapshot_version": snapshot.snapshot_version,
            "source_state_hash": state_hash,
            "snapshot_hash": snapshot_hash,
            **summary,
        },
        details=(
            "Built a source-linked, non-authoritative Claims Intelligence snapshot from controlled claim evidence, "
            "marine rules and structured Recovery & Time-bar evaluations."
        ),
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot

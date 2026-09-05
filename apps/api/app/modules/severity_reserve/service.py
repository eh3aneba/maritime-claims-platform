from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.claim_intelligence.models import ClaimIntelligenceItem
from app.modules.claim_intelligence.service import build_claim_intelligence
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.financial.models import CostItem, CostReviewStatus, FinancialFlag, ReserveHistory
from app.modules.financial.service import sync_financial_review
from app.modules.recovery_timebar.models import RecoveryTimebarEvaluation
from app.modules.severity_reserve import service_core as core
from app.modules.severity_reserve.models import SeverityReserveEvaluation, SeverityReserveSnapshot
from app.modules.users.models import User


for _name in dir(core):
    if not _name.startswith("__") and _name != "build_severity_reserve_support":
        globals()[_name] = getattr(core, _name)

ENGINE_VERSION = core.ENGINE_VERSION
DISCLAIMER = core.DISCLAIMER


def _quotation_summaries(items: list[CostItem]) -> list[dict]:
    groups: dict[tuple[UUID, str], dict] = {}
    for row in items:
        if row.document_kind != "quotation" or row.review_status == CostReviewStatus.REJECTED:
            continue
        currency = row.currency.upper()
        key = (row.document_id, currency)
        group = groups.setdefault(
            key,
            {
                "document_id": row.document_id,
                "supplier": row.supplier,
                "quotation_number": row.document_number,
                "currency": currency,
                "total": Decimal("0"),
            },
        )
        group["total"] += Decimal(row.amount)
        if not group.get("supplier") and row.supplier:
            group["supplier"] = row.supplier
        if not group.get("quotation_number") and row.document_number:
            group["quotation_number"] = row.document_number
    return list(groups.values())


def build_severity_reserve_support(db: Session, *, claim: Claim, user: User) -> SeverityReserveSnapshot:
    """Build non-authoritative reserve support from current source-admissible evidence.

    Refreshing Financial Review here only maintains the derived CostItem/flag cache from
    current usable source evidence. It never appends or changes a human CostReviewDecision
    and never writes authoritative ReserveHistory.
    """
    intelligence_snapshot = build_claim_intelligence(db, claim=claim, user=user)
    sync_financial_review(db, claim=claim, user_id=user.id)

    intelligence_items = list(
        db.scalars(
            select(ClaimIntelligenceItem)
            .where(ClaimIntelligenceItem.snapshot_id == intelligence_snapshot.id)
            .order_by(ClaimIntelligenceItem.rank_score.desc(), ClaimIntelligenceItem.item_key.asc())
        )
    )
    cost_items = list(
        db.scalars(
            select(CostItem)
            .where(CostItem.organization_id == claim.organization_id, CostItem.claim_id == claim.id)
            .order_by(CostItem.created_at.asc(), CostItem.id.asc())
        )
    )
    financial_flags = list(
        db.scalars(
            select(FinancialFlag)
            .where(FinancialFlag.organization_id == claim.organization_id, FinancialFlag.claim_id == claim.id)
            .order_by(FinancialFlag.created_at.asc(), FinancialFlag.id.asc())
        )
    )
    quotations = _quotation_summaries(cost_items)
    recovery_snapshot = core._latest_recovery_snapshot(db, claim)
    recovery_rows = (
        list(
            db.scalars(
                select(RecoveryTimebarEvaluation)
                .where(RecoveryTimebarEvaluation.snapshot_id == recovery_snapshot.id)
                .order_by(RecoveryTimebarEvaluation.kind.asc())
            )
        )
        if recovery_snapshot
        else []
    )
    facts = list(
        db.scalars(
            select(ClaimFact).where(
                ClaimFact.organization_id == claim.organization_id,
                ClaimFact.claim_id == claim.id,
            )
        )
    )
    current_reserve = db.scalar(
        select(ReserveHistory)
        .where(ReserveHistory.organization_id == claim.organization_id, ReserveHistory.claim_id == claim.id)
        .order_by(ReserveHistory.created_at.desc())
        .limit(1)
    )

    state = core._source_state(
        claim=claim,
        intelligence_snapshot=intelligence_snapshot,
        intelligence_items=intelligence_items,
        cost_items=cost_items,
        financial_flags=financial_flags,
        quotations=quotations,
        recovery_snapshot=recovery_snapshot,
        recovery_rows=recovery_rows,
        facts=facts,
        current_reserve=current_reserve,
    )
    source_state_hash = core._hash(state)
    existing = db.scalar(
        select(SeverityReserveSnapshot).where(
            SeverityReserveSnapshot.organization_id == claim.organization_id,
            SeverityReserveSnapshot.claim_id == claim.id,
            SeverityReserveSnapshot.source_state_hash == source_state_hash,
        )
    )
    if existing is not None:
        return existing

    severity = core._build_severity_evaluation(
        intelligence_items=intelligence_items,
        financial_flags=financial_flags,
        recovery_rows=recovery_rows,
    )
    reserve = core._build_reserve_evaluation(
        claim=claim,
        cost_items=cost_items,
        quotations=quotations,
        facts=facts,
        current_reserve=current_reserve,
    )
    payloads = [severity, reserve]
    summary = {
        "source_linked": True,
        "non_authoritative": True,
        "human_review_required": True,
        "handling_severity": severity["severity_label"],
        "handling_severity_score": severity["severity_score"],
        "reserve_range_status": reserve["status"],
        "reserve_currency": reserve["currency"],
        "reserve_lower_amount": str(reserve["lower_amount"]) if reserve["lower_amount"] is not None else None,
        "reserve_upper_amount": str(reserve["upper_amount"]) if reserve["upper_amount"] is not None else None,
        "reserve_history_updated": False,
        # Backward-compatible field: no human financial-review authority is mutated here.
        "financial_review_state_mutated": False,
        "financial_evidence_refreshed": True,
        "human_cost_review_decision_mutated": False,
        "coverage_decision_made": False,
        "liability_decision_made": False,
        "causation_decision_made": False,
        "settlement_or_payment_decision_made": False,
    }
    snapshot_hash = core._hash(
        {
            "engine": ENGINE_VERSION,
            "source_state_hash": source_state_hash,
            "summary": summary,
            "evaluation_hashes": [row["evaluation_hash"] for row in payloads],
        }
    )
    current_max = db.scalar(
        select(func.max(SeverityReserveSnapshot.snapshot_version)).where(
            SeverityReserveSnapshot.organization_id == claim.organization_id,
            SeverityReserveSnapshot.claim_id == claim.id,
        )
    ) or 0
    now = datetime.now(UTC)
    snapshot = SeverityReserveSnapshot(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        generated_by_id=user.id,
        snapshot_version=current_max + 1,
        engine_version=ENGINE_VERSION,
        source_state_hash=source_state_hash,
        snapshot_hash=snapshot_hash,
        summary=summary,
        generated_at=now,
    )
    db.add(snapshot)
    db.flush()
    for payload in payloads:
        db.add(
            SeverityReserveEvaluation(
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
        action="BUILD_SEVERITY_RESERVE_SUPPORT",
        entity_type="claim",
        entity_id=claim.id,
        new_values={
            "snapshot_id": str(snapshot.id),
            "snapshot_version": snapshot.snapshot_version,
            "snapshot_hash": snapshot_hash,
            **summary,
        },
        details=(
            "Built immutable source-linked handling severity and reserve-range support after refreshing current "
            "derived financial evidence. No human cost-review decision or authoritative reserve was changed."
        ),
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot

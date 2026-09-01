from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claim_intelligence.models import ClaimIntelligenceItem, ClaimIntelligenceSnapshot
from app.modules.claim_intelligence.service import build_claim_intelligence
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.financial.models import (
    CostItem,
    CostReviewStatus,
    FinancialFlag,
    FinancialFlagStatus,
    ReserveHistory,
)
from app.modules.financial.service import build_financial_review
from app.modules.recovery_timebar.models import RecoveryTimebarEvaluation, RecoveryTimebarSnapshot
from app.modules.severity_reserve.models import (
    SeverityReserveDecision,
    SeverityReserveEvaluation,
    SeverityReserveSnapshot,
)
from app.modules.severity_reserve.schemas import SeverityReserveDecisionWrite
from app.modules.users.models import User

ENGINE_VERSION = "12D.1"
DISCLAIMER = (
    "Severity & Reserve Support is source-linked decision support only. Handling severity is a workflow-priority signal, "
    "not a coverage, liability, causation or fraud conclusion. Any reserve range is a review aid derived from current "
    "controlled monetary evidence; it is not an authoritative reserve and never updates ReserveHistory automatically."
)

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("amount", value.get("value"))
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _fact_source(fact: ClaimFact) -> dict[str, Any]:
    return {
        "kind": "claim_fact",
        "id": str(fact.id),
        "field_path": fact.field_path,
        "document_id": str(fact.source_document_id),
        "extraction_id": str(fact.source_extraction_id),
        "segment_id": str(fact.source_segment_id) if fact.source_segment_id else None,
        "version": fact.version,
    }


def _latest_recovery_snapshot(db: Session, claim: Claim) -> RecoveryTimebarSnapshot | None:
    return db.scalar(
        select(RecoveryTimebarSnapshot)
        .where(
            RecoveryTimebarSnapshot.organization_id == claim.organization_id,
            RecoveryTimebarSnapshot.claim_id == claim.id,
        )
        .order_by(RecoveryTimebarSnapshot.snapshot_version.desc())
        .limit(1)
    )


def _latest_snapshot(db: Session, claim: Claim) -> SeverityReserveSnapshot | None:
    return db.scalar(
        select(SeverityReserveSnapshot)
        .where(
            SeverityReserveSnapshot.organization_id == claim.organization_id,
            SeverityReserveSnapshot.claim_id == claim.id,
        )
        .order_by(SeverityReserveSnapshot.snapshot_version.desc())
        .limit(1)
    )


def _snapshot_evaluations(db: Session, snapshot_id: UUID) -> list[SeverityReserveEvaluation]:
    return list(
        db.scalars(
            select(SeverityReserveEvaluation)
            .where(SeverityReserveEvaluation.snapshot_id == snapshot_id)
            .order_by(SeverityReserveEvaluation.kind.asc(), SeverityReserveEvaluation.evaluation_key.asc())
        )
    )


def _latest_decision(db: Session, evaluation_id: UUID) -> SeverityReserveDecision | None:
    return db.scalar(
        select(SeverityReserveDecision)
        .where(SeverityReserveDecision.evaluation_id == evaluation_id)
        .order_by(SeverityReserveDecision.decision_number.desc())
        .limit(1)
    )


def _severity_label(score: int) -> str:
    if score >= 10:
        return "critical"
    if score >= 6:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def _build_severity_evaluation(
    *,
    intelligence_items: list[ClaimIntelligenceItem],
    financial_flags: list[FinancialFlag],
    recovery_rows: list[RecoveryTimebarEvaluation],
) -> dict[str, Any]:
    factors: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    score = 0

    critical_items = [row for row in intelligence_items if row.severity == "critical"]
    high_items = [row for row in intelligence_items if row.severity == "high"]
    if critical_items:
        points = 4
        score += points
        factors.append({"factor": "critical_claim_intelligence", "points": points, "count": len(critical_items)})
        sources.extend(
            {"kind": "claim_intelligence_item", "id": str(row.id), "category": row.category, "severity": row.severity, "item_hash": row.item_hash}
            for row in critical_items[:5]
        )
    elif high_items:
        points = 2
        score += points
        factors.append({"factor": "high_claim_intelligence", "points": points, "count": len(high_items)})
        sources.extend(
            {"kind": "claim_intelligence_item", "id": str(row.id), "category": row.category, "severity": row.severity, "item_hash": row.item_hash}
            for row in high_items[:5]
        )

    open_high_flags = [row for row in financial_flags if row.status == FinancialFlagStatus.OPEN and row.severity == "high"]
    open_medium_flags = [row for row in financial_flags if row.status == FinancialFlagStatus.OPEN and row.severity == "medium"]
    if open_high_flags:
        points = 2
        score += points
        factors.append({"factor": "open_high_financial_flag", "points": points, "count": len(open_high_flags)})
        sources.extend(
            {"kind": "financial_flag", "id": str(row.id), "flag_type": row.flag_type.value, "severity": row.severity, "fingerprint": row.fingerprint}
            for row in open_high_flags[:5]
        )
    elif open_medium_flags:
        points = 1
        score += points
        factors.append({"factor": "open_medium_financial_flag", "points": points, "count": len(open_medium_flags)})
        sources.extend(
            {"kind": "financial_flag", "id": str(row.id), "flag_type": row.flag_type.value, "severity": row.severity, "fingerprint": row.fingerprint}
            for row in open_medium_flags[:5]
        )

    relevant_recovery = [row for row in recovery_rows if row.status in {"triggered", "insufficient_evidence"}]
    if relevant_recovery:
        max_urgency = max((row.urgency for row in relevant_recovery), key=lambda value: _SEVERITY_ORDER.get(value, 0))
        points = {"critical": 4, "high": 2, "medium": 1, "low": 0}.get(max_urgency, 0)
        if points:
            score += points
            factors.append({"factor": "recovery_timebar_urgency", "points": points, "urgency": max_urgency})
        sources.extend(
            {"kind": "recovery_timebar_evaluation", "id": str(row.id), "evaluation_hash": row.evaluation_hash, "status": row.status, "urgency": row.urgency}
            for row in relevant_recovery
        )

    conflicts = [row for row in intelligence_items if row.category == "conflict"]
    if conflicts:
        score += 2
        factors.append({"factor": "unresolved_conflict", "points": 2, "count": len(conflicts)})
        sources.extend(
            {"kind": "claim_intelligence_item", "id": str(row.id), "category": row.category, "severity": row.severity, "item_hash": row.item_hash}
            for row in conflicts[:5]
        )

    missing = [row for row in intelligence_items if row.category == "missing_evidence"]
    if missing:
        points = 2 if len(missing) >= 3 else 1
        score += points
        factors.append({"factor": "missing_evidence", "points": points, "count": len(missing)})
        sources.extend(
            {"kind": "claim_intelligence_item", "id": str(row.id), "category": row.category, "severity": row.severity, "item_hash": row.item_hash}
            for row in missing[:5]
        )

    label = _severity_label(score)
    if not factors:
        factors.append({"factor": "no_escalating_signal", "points": 0})
    payload = {
        "evaluation_key": "handling-severity",
        "kind": "severity",
        "status": "triggered",
        "title": "Claim handling severity",
        "severity_label": label,
        "severity_score": score,
        "currency": None,
        "lower_amount": None,
        "upper_amount": None,
        "rationale": (
            "Handling severity is a deterministic workflow-priority score derived from current source-linked operational signals. "
            "It does not predict coverage, liability, causation, fraud, settlement value or ultimate loss."
        ),
        "candidate_implication": f"Current handling priority is {label} based on an explainable score of {score}.",
        "recommended_action": "Review the listed factors and underlying evidence; adjust handling priority only through human judgment.",
        "factors": factors,
        "missing_prerequisites": [],
        "source_refs": sources,
    }
    payload["evaluation_hash"] = _hash(payload)
    return payload


def _estimate_facts(facts: list[ClaimFact]) -> tuple[Decimal | None, str | None, list[dict[str, Any]], list[str]]:
    by_path = {fact.field_path: fact for fact in facts}
    amount_fact = by_path.get("financial.estimated_repair_cost")
    currency_fact = by_path.get("financial.estimated_repair_cost_currency")
    amount = _decimal(amount_fact.value) if amount_fact else None
    currency = None
    if amount_fact and isinstance(amount_fact.value, dict):
        raw_currency = amount_fact.value.get("currency")
        currency = str(raw_currency).upper()[:3] if raw_currency else None
    if currency_fact and currency_fact.value:
        currency = str(currency_fact.value).upper()[:3]
    sources = [_fact_source(fact) for fact in (amount_fact, currency_fact) if fact is not None]
    missing: list[str] = []
    if amount_fact and amount is not None and not currency:
        missing.append("currency for approved repair-cost estimate")
    return amount, currency, sources, missing


def _build_reserve_evaluation(
    *,
    claim: Claim,
    cost_items: list[CostItem],
    quotations: list[dict[str, Any]],
    facts: list[ClaimFact],
    current_reserve: ReserveHistory | None,
) -> dict[str, Any]:
    target_currency = claim.currency.upper()
    invoice_items = [row for row in cost_items if row.document_kind == "invoice"]
    target_items = [row for row in invoice_items if row.currency.upper() == target_currency]
    foreign_items = [row for row in invoice_items if row.currency.upper() != target_currency]

    floor_items = [row for row in target_items if row.review_status in {CostReviewStatus.ACCEPTED, CostReviewStatus.PAID}]
    exposure_items = [row for row in target_items if row.review_status != CostReviewStatus.REJECTED]
    observed_floor = sum((Decimal(row.amount) for row in floor_items), Decimal("0"))
    non_rejected_total = sum((Decimal(row.amount) for row in exposure_items), Decimal("0"))

    quote_candidates: list[tuple[Decimal, dict[str, Any]]] = []
    foreign_quote_currencies: set[str] = set()
    quote_missing_currency = False
    for quote in quotations:
        total = _decimal(quote.get("total"))
        currency_raw = quote.get("currency")
        currency = str(currency_raw).upper()[:3] if currency_raw else None
        if total is None:
            continue
        if currency == target_currency:
            quote_candidates.append((total, quote))
        elif currency:
            foreign_quote_currencies.add(currency)
        else:
            quote_missing_currency = True

    estimate_amount, estimate_currency, estimate_sources, estimate_missing = _estimate_facts(facts)
    estimate_for_target = estimate_amount if estimate_amount is not None and estimate_currency == target_currency else None

    upper_candidates: list[Decimal] = []
    if exposure_items:
        upper_candidates.append(non_rejected_total)
    if quote_candidates:
        upper_candidates.append(max(value for value, _ in quote_candidates))
    if estimate_for_target is not None:
        upper_candidates.append(estimate_for_target)
    if floor_items and not upper_candidates:
        upper_candidates.append(observed_floor)

    sources: list[dict[str, Any]] = []
    for row in target_items:
        sources.append(
            {
                "kind": "cost_item",
                "id": str(row.id),
                "document_id": str(row.document_id),
                "review_status": row.review_status.value,
                "amount": str(row.amount),
                "currency": row.currency,
            }
        )
    for total, quote in quote_candidates:
        sources.append(
            {
                "kind": "reviewed_quotation",
                "document_id": str(quote.get("document_id")),
                "supplier": quote.get("supplier"),
                "amount": str(total),
                "currency": target_currency,
            }
        )
    sources.extend(estimate_sources)
    if current_reserve is not None:
        sources.append(
            {
                "kind": "reserve_history_context",
                "id": str(current_reserve.id),
                "amount": str(current_reserve.amount),
                "currency": current_reserve.currency,
                "created_at": current_reserve.created_at.isoformat(),
            }
        )

    excluded_currencies = sorted({row.currency.upper() for row in foreign_items} | foreign_quote_currencies)
    missing = list(estimate_missing)
    if excluded_currencies:
        missing.append("approved FX source required before using excluded currencies: " + ", ".join(excluded_currencies))
    if quote_missing_currency:
        missing.append("currency missing from one or more reviewed quotations")

    factors = [
        {"factor": "accepted_paid_invoice_floor", "amount": str(observed_floor), "currency": target_currency, "item_count": len(floor_items)},
        {"factor": "non_rejected_invoice_exposure", "amount": str(non_rejected_total), "currency": target_currency, "item_count": len(exposure_items)},
    ]
    if quote_candidates:
        factors.append({"factor": "highest_reviewed_quotation", "amount": str(max(value for value, _ in quote_candidates)), "currency": target_currency})
    if estimate_for_target is not None:
        factors.append({"factor": "approved_estimate_fact", "amount": str(estimate_for_target), "currency": target_currency})
    if current_reserve is not None:
        factors.append({"factor": "current_reserve_context_only", "amount": str(current_reserve.amount), "currency": current_reserve.currency})

    if not upper_candidates:
        status = "insufficient_evidence"
        lower = None
        upper = None
        missing.insert(0, f"reviewed monetary evidence in claim currency {target_currency}")
        implication = "No candidate reserve range is produced because current controlled evidence is insufficient."
    else:
        status = "triggered"
        lower = observed_floor
        upper = max(max(upper_candidates), observed_floor)
        implication = (
            f"Evidence-grounded reserve review range is {target_currency} {lower:.2f} to {upper:.2f}. "
            "The range is not an approved reserve and does not predict ultimate loss."
        )

    payload = {
        "evaluation_key": "reserve-range",
        "kind": "reserve",
        "status": status,
        "title": "Candidate reserve review range",
        "severity_label": None,
        "severity_score": None,
        "currency": target_currency,
        "lower_amount": lower,
        "upper_amount": upper,
        "rationale": (
            "The candidate range uses only current reviewed monetary evidence in the claim currency. Accepted/paid invoices form "
            "the observed floor; the upper evidence point is the maximum of non-rejected invoice exposure, reviewed quotation "
            "totals and a human-approved estimate fact. No FX conversion, deductible, limit or future-cost assumption is invented."
        ),
        "candidate_implication": implication,
        "recommended_action": (
            "Compare the range with the current human-set reserve and underlying evidence. Exercise reserve authority separately; "
            "this engine never creates or changes ReserveHistory."
        ),
        "factors": factors,
        "missing_prerequisites": missing,
        "source_refs": sources,
    }
    payload["evaluation_hash"] = _hash(payload)
    return payload


def _source_state(
    *,
    claim: Claim,
    intelligence_snapshot: ClaimIntelligenceSnapshot,
    intelligence_items: list[ClaimIntelligenceItem],
    cost_items: list[CostItem],
    financial_flags: list[FinancialFlag],
    quotations: list[dict[str, Any]],
    recovery_snapshot: RecoveryTimebarSnapshot | None,
    recovery_rows: list[RecoveryTimebarEvaluation],
    facts: list[ClaimFact],
    current_reserve: ReserveHistory | None,
) -> dict[str, Any]:
    relevant_facts = [fact for fact in facts if fact.field_path.startswith("financial.estimated_repair_cost")]
    return {
        "claim": {"id": str(claim.id), "status": claim.status.value, "currency": claim.currency},
        "claims_intelligence": {
            "snapshot_id": str(intelligence_snapshot.id),
            "snapshot_hash": intelligence_snapshot.snapshot_hash,
            "items": [
                {"id": str(row.id), "category": row.category, "severity": row.severity, "item_hash": row.item_hash}
                for row in intelligence_items
            ],
        },
        "financial": {
            "cost_items": [
                {
                    "id": str(row.id),
                    "document_id": str(row.document_id),
                    "kind": row.document_kind,
                    "amount": str(row.amount),
                    "currency": row.currency,
                    "status": row.review_status.value,
                }
                for row in cost_items
            ],
            "flags": [
                {
                    "id": str(row.id),
                    "type": row.flag_type.value,
                    "severity": row.severity,
                    "status": row.status.value,
                    "fingerprint": row.fingerprint,
                }
                for row in financial_flags
            ],
            "quotations": [_jsonable(row) for row in quotations],
        },
        "recovery_timebar": {
            "snapshot_id": str(recovery_snapshot.id) if recovery_snapshot else None,
            "snapshot_hash": recovery_snapshot.snapshot_hash if recovery_snapshot else None,
            "evaluations": [
                {"id": str(row.id), "status": row.status, "urgency": row.urgency, "evaluation_hash": row.evaluation_hash}
                for row in recovery_rows
            ],
        },
        "estimate_facts": [
            {"id": str(fact.id), "field_path": fact.field_path, "value": _jsonable(fact.value), "version": fact.version}
            for fact in relevant_facts
        ],
        "current_reserve": (
            {
                "id": str(current_reserve.id),
                "amount": str(current_reserve.amount),
                "currency": current_reserve.currency,
                "created_at": current_reserve.created_at.isoformat(),
            }
            if current_reserve
            else None
        ),
        "engine_version": ENGINE_VERSION,
    }


def snapshot_response(db: Session, snapshot: SeverityReserveSnapshot) -> dict[str, Any]:
    evaluations = []
    for row in _snapshot_evaluations(db, snapshot.id):
        evaluations.append(
            {
                "id": row.id,
                "snapshot_id": row.snapshot_id,
                "evaluation_key": row.evaluation_key,
                "kind": row.kind,
                "status": row.status,
                "title": row.title,
                "severity_label": row.severity_label,
                "severity_score": row.severity_score,
                "currency": row.currency,
                "lower_amount": row.lower_amount,
                "upper_amount": row.upper_amount,
                "rationale": row.rationale,
                "candidate_implication": row.candidate_implication,
                "recommended_action": row.recommended_action,
                "factors": list(row.factors or []),
                "missing_prerequisites": list(row.missing_prerequisites or []),
                "source_refs": list(row.source_refs or []),
                "evaluation_hash": row.evaluation_hash,
                "latest_decision": _latest_decision(db, row.id),
            }
        )
    return {
        "id": snapshot.id,
        "claim_id": snapshot.claim_id,
        "generated_by_id": snapshot.generated_by_id,
        "snapshot_version": snapshot.snapshot_version,
        "engine_version": snapshot.engine_version,
        "source_state_hash": snapshot.source_state_hash,
        "snapshot_hash": snapshot.snapshot_hash,
        "summary": dict(snapshot.summary or {}),
        "generated_at": snapshot.generated_at,
        "evaluations": evaluations,
    }


def dashboard_response(db: Session, *, claim: Claim) -> dict[str, Any]:
    snapshot = _latest_snapshot(db, claim)
    return {"claim_id": claim.id, "snapshot": snapshot_response(db, snapshot) if snapshot else None, "disclaimer": DISCLAIMER}


def build_severity_reserve_support(db: Session, *, claim: Claim, user: User) -> SeverityReserveSnapshot:
    intelligence_snapshot = build_claim_intelligence(db, claim=claim, user=user)
    financial = build_financial_review(db, claim=claim, user_id=user.id)
    db.flush()

    intelligence_items = list(
        db.scalars(
            select(ClaimIntelligenceItem)
            .where(ClaimIntelligenceItem.snapshot_id == intelligence_snapshot.id)
            .order_by(ClaimIntelligenceItem.rank_score.desc(), ClaimIntelligenceItem.item_key.asc())
        )
    )
    cost_items = list(financial["items"])
    financial_flags = list(financial["flags"])
    quotations = list(financial["quotations"])
    recovery_snapshot = _latest_recovery_snapshot(db, claim)
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

    state = _source_state(
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
    source_state_hash = _hash(state)
    existing = db.scalar(
        select(SeverityReserveSnapshot).where(
            SeverityReserveSnapshot.organization_id == claim.organization_id,
            SeverityReserveSnapshot.claim_id == claim.id,
            SeverityReserveSnapshot.source_state_hash == source_state_hash,
        )
    )
    if existing is not None:
        return existing

    severity = _build_severity_evaluation(
        intelligence_items=intelligence_items,
        financial_flags=financial_flags,
        recovery_rows=recovery_rows,
    )
    reserve = _build_reserve_evaluation(
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
        "coverage_decision_made": False,
        "liability_decision_made": False,
        "causation_decision_made": False,
        "settlement_or_payment_decision_made": False,
    }
    snapshot_hash = _hash(
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
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="BUILD_SEVERITY_RESERVE_SUPPORT",
        entity_type="claim",
        entity_id=claim.id,
        new_values={"snapshot_id": str(snapshot.id), "snapshot_version": snapshot.snapshot_version, "snapshot_hash": snapshot_hash, **summary},
        details="Built immutable source-linked handling severity and reserve-range support without changing authoritative reserve state.",
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot


def record_decision(
    db: Session,
    *,
    claim: Claim,
    evaluation: SeverityReserveEvaluation,
    payload: SeverityReserveDecisionWrite,
    user: User,
) -> SeverityReserveDecision:
    if evaluation.organization_id != claim.organization_id or evaluation.claim_id != claim.id:
        raise ValueError("Severity/reserve evaluation does not belong to this claim")
    latest_snapshot = _latest_snapshot(db, claim)
    if latest_snapshot is None or latest_snapshot.id != evaluation.snapshot_id:
        raise ValueError("Severity/reserve evaluation belongs to a superseded snapshot; review the latest snapshot instead")
    if payload.evaluation_hash != evaluation.evaluation_hash:
        raise ValueError("Evaluation hash does not match the immutable evaluation under review")
    if evaluation.kind == "severity" and (payload.edited_lower_amount is not None or payload.edited_upper_amount is not None):
        raise ValueError("Reserve amount edits are not valid for a severity evaluation")
    if evaluation.kind == "reserve" and payload.edited_severity_label is not None:
        raise ValueError("Severity edits are not valid for a reserve evaluation")

    previous = _latest_decision(db, evaluation.id)
    number = (previous.decision_number + 1) if previous else 1
    now = datetime.now(UTC)
    decision_payload = {
        "snapshot_id": str(evaluation.snapshot_id),
        "evaluation_hash": evaluation.evaluation_hash,
        "decision_number": number,
        "action": payload.action,
        "note": payload.note.strip(),
        "edited_severity_label": payload.edited_severity_label,
        "edited_lower_amount": str(payload.edited_lower_amount) if payload.edited_lower_amount is not None else None,
        "edited_upper_amount": str(payload.edited_upper_amount) if payload.edited_upper_amount is not None else None,
        "previous_decision_hash": previous.decision_hash if previous else None,
        "decided_by_id": str(user.id),
        "decided_at": now.isoformat(),
    }
    decision = SeverityReserveDecision(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        snapshot_id=evaluation.snapshot_id,
        evaluation_id=evaluation.id,
        decided_by_id=user.id,
        evaluation_hash=evaluation.evaluation_hash,
        decision_number=number,
        action=payload.action,
        note=payload.note.strip(),
        edited_severity_label=payload.edited_severity_label,
        edited_lower_amount=payload.edited_lower_amount,
        edited_upper_amount=payload.edited_upper_amount,
        previous_decision_hash=previous.decision_hash if previous else None,
        decision_hash=_hash(decision_payload),
        decided_at=now,
    )
    db.add(decision)
    db.flush()
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="REVIEW_SEVERITY_RESERVE_SUPPORT",
        entity_type="severity_reserve_evaluation",
        entity_id=evaluation.id,
        new_values={
            "snapshot_id": str(evaluation.snapshot_id),
            "decision_id": str(decision.id),
            "decision_number": number,
            "action": payload.action,
            "decision_hash": decision.decision_hash,
            "reserve_history_updated": False,
        },
        details="Human disposition recorded separately from immutable severity/reserve support; authoritative reserve state was not changed.",
    )
    db.commit()
    db.refresh(decision)
    return decision

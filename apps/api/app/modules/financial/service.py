from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.documents.models import (
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.financial.models import (
    CostItem,
    CostReviewDecision,
    CostReviewStatus,
    FinancialFlag,
    FinancialFlagStatus,
    FinancialFlagType,
    ReserveHistory,
)
from app.modules.intelligence.models import (
    AIRun,
    AIRunStatus,
    AIReviewStatus,
    DocumentExtraction,
)

_REVIEWED = (AIReviewStatus.APPROVED, AIReviewStatus.EDITED)
_USABLE_MALWARE_STATES = (
    DocumentMalwareScanStatus.CLEAN,
    DocumentMalwareScanStatus.LEGACY_UNSCANNED,
)


class CostReviewConflictError(ValueError):
    pass


def _val(row: DocumentExtraction | None):
    if row is None:
        return None
    if row.human_status == AIReviewStatus.EDITED:
        return row.approved_value
    return row.normalized_value if row.normalized_value is not None else row.raw_value


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict) and "raw" in value:
        return str(value["raw"])
    return str(value)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip()
    token = re.search(r"[-+]?\d[\d,.]*", text)
    if not token:
        return None
    raw = token.group(0)
    if raw.count(",") and raw.count("."):
        if raw.rfind(".") > raw.rfind(","):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
        raw = raw.replace(",", "")
    elif raw.count(",") == 1 and len(raw.split(",")[-1]) <= 2:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value") and isinstance(getattr(value, "value"), (str, int, float, bool)):
        return value.value
    return value


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _reviewed_rows(db: Session, run: AIRun) -> dict[str, DocumentExtraction]:
    return {
        row.field_path: row
        for row in db.scalars(
            select(DocumentExtraction).where(
                DocumentExtraction.ai_run_id == run.id,
                DocumentExtraction.organization_id == run.organization_id,
                DocumentExtraction.claim_id == run.claim_id,
                DocumentExtraction.document_id == run.document_id,
                DocumentExtraction.human_status.in_(_REVIEWED),
            )
        )
    }


def _latest_completed_runs(
    db: Session,
    claim: Claim,
    tasks: list[str],
) -> list[tuple[AIRun, Document]]:
    rows = db.execute(
        select(AIRun, Document)
        .join(Document, Document.id == AIRun.document_id)
        .where(
            AIRun.claim_id == claim.id,
            AIRun.organization_id == claim.organization_id,
            AIRun.task.in_(tasks),
            AIRun.status == AIRunStatus.COMPLETED,
            Document.organization_id == claim.organization_id,
            Document.claim_id == claim.id,
            Document.is_current.is_(True),
            Document.deleted_at.is_(None),
            Document.processing_status == DocumentProcessingStatus.PROCESSED,
            Document.malware_scan_status.in_(_USABLE_MALWARE_STATES),
        )
        .order_by(AIRun.created_at.desc(), AIRun.id.desc())
    ).all()
    seen: set[UUID] = set()
    output: list[tuple[AIRun, Document]] = []
    for run, document in rows:
        if run.document_id in seen:
            continue
        seen.add(run.document_id)
        output.append((run, document))
    return output


def _item_key(document: Document, kind: str, source_field_prefix: str) -> str:
    stable = f"{document.document_family_id}|{kind}|{source_field_prefix}"
    return "cost_" + hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _item_snapshot(item: CostItem, document: Document, run: AIRun) -> dict[str, Any]:
    return {
        "item_key": _item_key(document, item.document_kind, item.source_field_prefix),
        "document_id": document.id,
        "document_family_id": document.document_family_id,
        "document_version": document.version_number,
        "document_file_hash": document.file_hash,
        "document_is_current": document.is_current and document.deleted_at is None,
        "document_processing_status": document.processing_status.value,
        "document_malware_scan_status": document.malware_scan_status.value,
        "source_state": "current_usable",
        "ai_run_id": run.id,
        "ai_input_text_hash": run.input_text_hash,
        "ai_task": run.task,
        "ai_prompt_version": run.prompt_version,
        "ai_schema_version": run.schema_version,
        "line_index": item.line_index,
        "document_kind": item.document_kind,
        "supplier": item.supplier,
        "document_number": item.document_number,
        "document_date": item.document_date,
        "description": item.description,
        "quantity": item.quantity,
        "unit": item.unit,
        "unit_price": item.unit_price,
        "amount": item.amount,
        "currency": item.currency,
        "category": item.category,
        "source_field_prefix": item.source_field_prefix,
    }


def _decision_payload(decision: CostReviewDecision) -> dict[str, Any]:
    return {
        "id": decision.id,
        "item_key": decision.item_key,
        "state_fingerprint": decision.state_fingerprint,
        "state_version": decision.state_version,
        "decision_number": decision.decision_number,
        "status": decision.status,
        "reason": decision.reason,
        "item_snapshot": decision.item_snapshot,
        "reviewed_by_id": decision.reviewed_by_id,
        "reviewed_at": decision.reviewed_at,
        "previous_decision_hash": decision.previous_decision_hash,
        "decision_hash": decision.decision_hash,
    }


def _decision_hash(
    *,
    organization_id: UUID,
    claim_id: UUID,
    item_key: str,
    state_fingerprint: str,
    state_version: int,
    decision_number: int,
    status: str,
    reason: str,
    item_snapshot: dict[str, Any],
    reviewed_by_id: UUID | None,
    previous_decision_hash: str | None,
) -> str:
    return _hash(
        {
            "organization_id": organization_id,
            "claim_id": claim_id,
            "item_key": item_key,
            "state_fingerprint": state_fingerprint,
            "state_version": state_version,
            "decision_number": decision_number,
            "status": status,
            "reason": reason,
            "item_snapshot": item_snapshot,
            "reviewed_by_id": reviewed_by_id,
            "previous_decision_hash": previous_decision_hash,
        }
    )


def _decision_history(
    db: Session,
    *,
    claim: Claim,
    item_key: str | None = None,
) -> list[CostReviewDecision]:
    stmt = select(CostReviewDecision).where(
        CostReviewDecision.organization_id == claim.organization_id,
        CostReviewDecision.claim_id == claim.id,
    )
    if item_key is not None:
        stmt = stmt.where(CostReviewDecision.item_key == item_key)
    stmt = stmt.order_by(CostReviewDecision.item_key.asc(), CostReviewDecision.decision_number.asc())
    return list(db.scalars(stmt))


def _item_source_maps(
    db: Session,
    *,
    claim: Claim,
    items: list[CostItem],
) -> tuple[dict[UUID, Document], dict[UUID, AIRun]]:
    document_ids = {item.document_id for item in items}
    run_ids = {item.ai_run_id for item in items}
    documents = {
        row.id: row
        for row in db.scalars(
            select(Document).where(
                Document.organization_id == claim.organization_id,
                Document.claim_id == claim.id,
                Document.id.in_(document_ids),
            )
        )
    } if document_ids else {}
    runs = {
        row.id: row
        for row in db.scalars(
            select(AIRun).where(
                AIRun.organization_id == claim.organization_id,
                AIRun.claim_id == claim.id,
                AIRun.id.in_(run_ids),
            )
        )
    } if run_ids else {}
    return documents, runs


def _cost_item_state(
    *,
    item: CostItem,
    document: Document,
    run: AIRun,
    latest: CostReviewDecision | None,
) -> dict[str, Any]:
    snapshot = _item_snapshot(item, document, run)
    fingerprint = _hash(snapshot)
    if latest is None:
        state_version = 1
        decision_state = "none"
    elif latest.state_fingerprint == fingerprint:
        state_version = latest.state_version
        decision_state = "current"
    else:
        state_version = latest.state_version + 1
        decision_state = "stale"
    return {
        "item_key": snapshot["item_key"],
        "snapshot": snapshot,
        "state_fingerprint": fingerprint,
        "state_version": state_version,
        "decision_state": decision_state,
    }


def _sync_current_review_cache(
    db: Session,
    *,
    claim: Claim,
    items: list[CostItem],
) -> dict[UUID, dict[str, Any]]:
    history = _decision_history(db, claim=claim)
    grouped: dict[str, list[CostReviewDecision]] = defaultdict(list)
    for decision in history:
        grouped[decision.item_key].append(decision)
    latest = {key: rows[-1] for key, rows in grouped.items()}
    documents, runs = _item_source_maps(db, claim=claim, items=items)
    states: dict[UUID, dict[str, Any]] = {}
    for item in items:
        document = documents.get(item.document_id)
        run = runs.get(item.ai_run_id)
        if document is None or run is None:
            continue
        key = _item_key(document, item.document_kind, item.source_field_prefix)
        state = _cost_item_state(item=item, document=document, run=run, latest=latest.get(key))
        state["history"] = grouped.get(key, [])
        state["latest_decision"] = latest.get(key)
        states[item.id] = state
        prior = latest.get(key)
        if prior is not None and state["decision_state"] == "current":
            item.review_status = CostReviewStatus(prior.status)
        elif prior is not None and state["decision_state"] == "stale":
            # Never allow a prior accepted/rejected/paid status to flow into a changed source state.
            item.review_status = CostReviewStatus.UNDER_REVIEW
    db.flush()
    return states


def sync_financial_review(
    db: Session,
    *,
    claim: Claim,
    user_id: UUID | None = None,
) -> dict[UUID, dict[str, Any]]:
    from app.modules.intelligence.service import TASK_INVOICE, TASK_QUOTATION

    run_rows = _latest_completed_runs(db, claim, [TASK_QUOTATION, TASK_INVOICE])
    existing = {
        (item.ai_run_id, item.source_field_prefix): item
        for item in db.scalars(
            select(CostItem).where(
                CostItem.claim_id == claim.id,
                CostItem.organization_id == claim.organization_id,
            )
        )
    }
    keep: set[tuple[UUID, str]] = set()

    for run, document in run_rows:
        rows = _reviewed_rows(db, run)
        kind = "quotation" if run.task == TASK_QUOTATION else "invoice"
        prefix = "quotation.line_items" if kind == "quotation" else "invoice.line_items"
        supplier = _as_text(_val(rows.get(f"{kind}.supplier")))
        number_field = "quotation_number" if kind == "quotation" else "invoice_number"
        date_field = "quotation_date" if kind == "quotation" else "invoice_date"
        number = _as_text(_val(rows.get(f"{kind}.{number_field}")))
        document_date = _date(_val(rows.get(f"{kind}.{date_field}")))
        currency = (_as_text(_val(rows.get(f"{kind}.currency"))) or claim.currency).upper()[:3]
        indices = sorted(
            {
                int(match.group(1))
                for path in rows
                for match in [re.match(rf"^{re.escape(prefix)}\[(\d+)\]\.description$", path)]
                if match
            }
        )
        for index in indices:
            base = f"{prefix}[{index}]"
            description = _as_text(_val(rows.get(base + ".description")))
            amount = _decimal(_val(rows.get(base + ".amount")))
            if not description or amount is None or amount < 0:
                continue
            key = (run.id, base)
            keep.add(key)
            item = existing.get(key)
            if item is None:
                item = CostItem(
                    organization_id=claim.organization_id,
                    claim_id=claim.id,
                    document_id=document.id,
                    ai_run_id=run.id,
                    line_index=index,
                    document_kind=kind,
                    description=description,
                    amount=amount,
                    currency=currency,
                    source_field_prefix=base,
                    review_status=CostReviewStatus.UNDER_REVIEW,
                )
                db.add(item)
            item.document_id = document.id
            item.supplier = supplier
            item.document_number = number
            item.document_date = document_date
            item.description = description
            item.amount = amount
            item.currency = currency
            item.quantity = _decimal(_val(rows.get(base + ".quantity")))
            item.unit = _as_text(_val(rows.get(base + ".unit")))
            item.unit_price = _decimal(_val(rows.get(base + ".unit_price")))
            item.category = _as_text(_val(rows.get(base + ".category_candidate")))

    for key, item in existing.items():
        if key not in keep:
            db.delete(item)

    db.flush()
    _sync_flags(db, claim=claim, runs=run_rows)
    items = list(
        db.scalars(
            select(CostItem)
            .where(
                CostItem.claim_id == claim.id,
                CostItem.organization_id == claim.organization_id,
            )
            .order_by(CostItem.created_at.asc(), CostItem.id.asc())
        )
    )
    states = _sync_current_review_cache(db, claim=claim, items=items)
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user_id,
        action="SYNC_FINANCIAL_REVIEW",
        entity_type="claim",
        entity_id=claim.id,
        new_values={
            "current_usable_source_runs": len(run_rows),
            "current_cost_items": len(items),
            "stale_cost_reviews": sum(1 for state in states.values() if state["decision_state"] == "stale"),
        },
        details="Refreshed derived financial evidence from current usable source documents without making a coverage, recoverability, reserve, settlement or payment decision.",
    )
    return states


def _upsert_flag(
    db: Session,
    claim: Claim,
    *,
    flag_type: FinancialFlagType,
    fingerprint: str,
    severity: str,
    title: str,
    explanation: str,
    evidence: dict,
):
    row = db.scalar(
        select(FinancialFlag).where(
            FinancialFlag.claim_id == claim.id,
            FinancialFlag.organization_id == claim.organization_id,
            FinancialFlag.fingerprint == fingerprint,
        )
    )
    if row is None:
        row = FinancialFlag(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            flag_type=flag_type,
            fingerprint=fingerprint,
            severity=severity,
            title=title,
            explanation=explanation,
            evidence=evidence,
        )
        db.add(row)
    else:
        row.severity = severity
        row.title = title
        row.explanation = explanation
        row.evidence = evidence
    return row


def _sync_flags(db: Session, *, claim: Claim, runs: list[tuple[AIRun, Document]]):
    from app.modules.intelligence.service import TASK_INVOICE

    live: set[str] = set()
    headers = []
    for run, document in runs:
        rows = _reviewed_rows(db, run)
        kind = "quotation" if run.task != TASK_INVOICE else "invoice"
        number = _as_text(
            _val(rows.get(f"{kind}.{'quotation_number' if kind == 'quotation' else 'invoice_number'}"))
        )
        supplier = _as_text(_val(rows.get(f"{kind}.supplier")))
        total = _decimal(_val(rows.get(f"{kind}.total")))
        document_date = _date(
            _val(rows.get(f"{kind}.{'quotation_date' if kind == 'quotation' else 'invoice_date'}"))
        )
        headers.append((run, document, kind, number, supplier, total, document_date, rows))
        if kind == "invoice" and document_date and document_date < claim.incident_date:
            fingerprint = f"invoice-date:{document.document_family_id}"
            live.add(fingerprint)
            _upsert_flag(
                db,
                claim,
                flag_type=FinancialFlagType.INVOICE_PREDATES_INCIDENT,
                fingerprint=fingerprint,
                severity="medium",
                title="Invoice predates reported casualty",
                explanation=(
                    "The reviewed invoice date is earlier than the claim incident date. Review whether this is an "
                    "advance/previous transaction or data issue; do not reject automatically."
                ),
                evidence={
                    "invoice_date": document_date.isoformat(),
                    "incident_date": claim.incident_date.isoformat(),
                    "document_id": str(document.id),
                    "document_version": document.version_number,
                },
            )
        prefix = f"{kind}.line_items"
        indices = sorted(
            {
                int(match.group(1))
                for path in rows
                for match in [re.match(rf"^{re.escape(prefix)}\[(\d+)\]\.description$", path)]
                if match
            }
        )
        for index in indices:
            for leaf, flag_type, title in [
                (
                    "potential_betterment_cue",
                    FinancialFlagType.POTENTIAL_BETTERMENT,
                    "Potential betterment / upgrade cue",
                ),
                (
                    "potential_ordinary_maintenance_cue",
                    FinancialFlagType.POTENTIAL_ORDINARY_MAINTENANCE,
                    "Potential ordinary maintenance item",
                ),
            ]:
                if _val(rows.get(f"{prefix}[{index}].{leaf}")) is True:
                    fingerprint = f"{flag_type.value}:{document.document_family_id}:{index}"
                    live.add(fingerprint)
                    description = _as_text(_val(rows.get(f"{prefix}[{index}].description")))
                    _upsert_flag(
                        db,
                        claim,
                        flag_type=flag_type,
                        fingerprint=fingerprint,
                        severity="medium",
                        title=title,
                        explanation=(
                            "This is a review cue from human-reviewed source evidence, not a recoverability decision."
                        ),
                        evidence={
                            "document_id": str(document.id),
                            "document_version": document.version_number,
                            "line_index": index,
                            "description": description,
                        },
                    )

    invoices = [header for header in headers if header[2] == "invoice"]
    for index, left in enumerate(invoices):
        for right in invoices[index + 1 :]:
            if (
                left[3]
                and right[3]
                and left[4]
                and right[4]
                and left[3].casefold() == right[3].casefold()
                and left[4].casefold() == right[4].casefold()
                and left[5] is not None
                and left[5] == right[5]
            ):
                family_ids = sorted([str(left[1].document_family_id), str(right[1].document_family_id)])
                fingerprint = "duplicate:" + hashlib.sha1("|".join(family_ids).encode()).hexdigest()
                live.add(fingerprint)
                _upsert_flag(
                    db,
                    claim,
                    flag_type=FinancialFlagType.POSSIBLE_DUPLICATE,
                    fingerprint=fingerprint,
                    severity="high",
                    title="Probable duplicate invoice",
                    explanation=(
                        "Reviewed supplier, invoice number and total match across two invoice documents. Human review "
                        "is required before any duplicate conclusion."
                    ),
                    evidence={
                        "document_ids": [str(left[1].id), str(right[1].id)],
                        "invoice_number": left[3],
                        "supplier": left[4],
                        "total": str(left[5]),
                    },
                )

    quotes = [header for header in headers if header[2] == "quotation"]
    if len(quotes) >= 2:
        scopes = []
        for header in quotes:
            scope = _as_text(_val(header[7].get("quotation.scope_summary")))
            if scope:
                scopes.append((header, scope))
        if len(scopes) >= 2 and len({re.sub(r"\s+", " ", scope.casefold()).strip() for _, scope in scopes}) > 1:
            family_ids = sorted(str(header[1].document_family_id) for header, _ in scopes)
            fingerprint = "quote-scope:" + hashlib.sha1("|".join(family_ids).encode()).hexdigest()
            live.add(fingerprint)
            _upsert_flag(
                db,
                claim,
                flag_type=FinancialFlagType.QUOTE_SCOPE_DIFFERENCE,
                fingerprint=fingerprint,
                severity="high",
                title="Material quotation scope difference",
                explanation=(
                    "Reviewed quotation scopes are not the same. Technical justification is required before "
                    "price-only comparison; the system does not select a supplier."
                ),
                evidence={
                    "quotes": [
                        {
                            "document_id": str(header[1].id),
                            "document_version": header[1].version_number,
                            "supplier": header[4],
                            "scope": scope,
                            "total": str(header[5]) if header[5] is not None else None,
                        }
                        for header, scope in scopes
                    ]
                },
            )

    for flag in db.scalars(
        select(FinancialFlag).where(
            FinancialFlag.claim_id == claim.id,
            FinancialFlag.organization_id == claim.organization_id,
            FinancialFlag.status == FinancialFlagStatus.OPEN,
        )
    ):
        if flag.fingerprint not in live:
            flag.status = FinancialFlagStatus.IRRELEVANT
            flag.resolution_note = "Underlying current usable reviewed evidence no longer triggers this deterministic flag."
            flag.resolved_at = datetime.now(UTC)


def _current_items_and_states(
    db: Session,
    *,
    claim: Claim,
    user_id: UUID | None,
) -> tuple[list[CostItem], dict[UUID, dict[str, Any]]]:
    states = sync_financial_review(db, claim=claim, user_id=user_id)
    items = list(
        db.scalars(
            select(CostItem)
            .where(
                CostItem.claim_id == claim.id,
                CostItem.organization_id == claim.organization_id,
            )
            .order_by(CostItem.created_at.asc(), CostItem.id.asc())
        )
    )
    return items, states


def build_financial_review(
    db: Session,
    *,
    claim: Claim,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    items, states = _current_items_and_states(db, claim=claim, user_id=user_id)
    flags = list(
        db.scalars(
            select(FinancialFlag)
            .where(
                FinancialFlag.claim_id == claim.id,
                FinancialFlag.organization_id == claim.organization_id,
            )
            .order_by(FinancialFlag.created_at.desc())
        )
    )
    reserves = list(
        db.scalars(
            select(ReserveHistory)
            .where(
                ReserveHistory.claim_id == claim.id,
                ReserveHistory.organization_id == claim.organization_id,
            )
            .order_by(ReserveHistory.created_at.desc())
        )
    )

    totals: dict[str, Decimal] = {}
    current_rows: list[dict[str, Any]] = []
    current_keys: set[str] = set()
    for item in items:
        if item.document_kind == "invoice":
            totals[item.currency] = totals.get(item.currency, Decimal("0")) + item.amount
        state = states.get(item.id)
        if state is None:
            continue
        current_keys.add(state["item_key"])
        snapshot = state["snapshot"]
        current_rows.append(
            {
                "id": item.id,
                "document_id": item.document_id,
                "document_family_id": snapshot["document_family_id"],
                "document_version": snapshot["document_version"],
                "document_is_current": snapshot["document_is_current"],
                "document_processing_status": snapshot["document_processing_status"],
                "document_malware_scan_status": snapshot["document_malware_scan_status"],
                "source_state": snapshot["source_state"],
                "document_kind": item.document_kind,
                "supplier": item.supplier,
                "document_number": item.document_number,
                "document_date": item.document_date,
                "line_index": item.line_index,
                "description": item.description,
                "quantity": item.quantity,
                "unit": item.unit,
                "unit_price": item.unit_price,
                "amount": item.amount,
                "currency": item.currency,
                "category": item.category,
                "review_status": item.review_status,
                "item_key": state["item_key"],
                "state_fingerprint": state["state_fingerprint"],
                "state_version": state["state_version"],
                "decision_state": state["decision_state"],
                "latest_review_decision": (
                    _decision_payload(state["latest_decision"]) if state["latest_decision"] is not None else None
                ),
                "review_history": [_decision_payload(decision) for decision in state["history"]],
            }
        )

    all_history = _decision_history(db, claim=claim)
    latest_by_key: dict[str, CostReviewDecision] = {}
    for decision in all_history:
        latest_by_key[decision.item_key] = decision
    historical_reviews = [
        {
            "item_key": item_key,
            "decision_state": "stale",
            "current_source_available": False,
            "latest_review_decision": _decision_payload(decision),
            "message": (
                "The source evidence previously reviewed for this cost item is no longer present in the current "
                "usable financial evidence state. The historical human disposition is retained for audit only and "
                "does not apply to a replacement source automatically."
            ),
        }
        for item_key, decision in latest_by_key.items()
        if item_key not in current_keys
    ]

    quotations = []
    from app.modules.intelligence.service import TASK_QUOTATION

    for run, document in _latest_completed_runs(db, claim, [TASK_QUOTATION]):
        rows = _reviewed_rows(db, run)
        line_items = [
            {
                "description": item.description,
                "amount": str(item.amount),
                "currency": item.currency,
                "category": item.category,
            }
            for item in items
            if item.ai_run_id == run.id
        ]
        quotations.append(
            {
                "document_id": document.id,
                "document_version": document.version_number,
                "supplier": _as_text(_val(rows.get("quotation.supplier"))),
                "quotation_number": _as_text(_val(rows.get("quotation.quotation_number"))),
                "currency": _as_text(_val(rows.get("quotation.currency"))),
                "total": _decimal(_val(rows.get("quotation.total"))),
                "scope_summary": _as_text(_val(rows.get("quotation.scope_summary"))),
                "lead_time": _as_text(_val(rows.get("quotation.lead_time"))),
                "repair_duration": _as_text(_val(rows.get("quotation.repair_duration"))),
                "line_items": line_items,
            }
        )

    return {
        "claim_id": claim.id,
        "totals_by_currency": totals,
        "items": current_rows,
        "flags": flags,
        "quotations": quotations,
        "reserve_history": reserves,
        "historical_reviews": historical_reviews,
        "summary": {
            "current_item_count": len(current_rows),
            "current_decision_count": sum(1 for row in current_rows if row["decision_state"] == "current"),
            "stale_decision_count": sum(1 for row in current_rows if row["decision_state"] == "stale")
            + len(historical_reviews),
            "unreviewed_item_count": sum(1 for row in current_rows if row["decision_state"] == "none"),
        },
    }


def record_cost_review_decision(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
    item_id: UUID,
    status: CostReviewStatus,
    reason: str,
    expected_state_fingerprint: str,
    expected_state_version: int,
    confirm_re_review: bool,
    user_id: UUID,
) -> CostReviewDecision:
    claim = db.scalar(
        select(Claim)
        .where(Claim.id == claim_id, Claim.organization_id == organization_id)
        .with_for_update()
    )
    if claim is None:
        raise CostReviewConflictError("Claim is no longer available for this financial review.")

    states = sync_financial_review(db, claim=claim, user_id=user_id)
    item = db.get(CostItem, item_id)
    if item is None or item.claim_id != claim.id or item.organization_id != organization_id:
        raise CostReviewConflictError(
            "Financial evidence changed and this cost item is no longer current. Refresh the financial review."
        )
    state = states.get(item.id)
    if state is None:
        raise CostReviewConflictError("Current financial evidence state is unavailable. Refresh the financial review.")
    if (
        state["state_fingerprint"] != expected_state_fingerprint
        or state["state_version"] != expected_state_version
    ):
        raise CostReviewConflictError(
            "Financial evidence changed while this cost item was being reviewed. Refresh before recording a disposition."
        )

    history: list[CostReviewDecision] = state["history"]
    latest = history[-1] if history else None
    clean_reason = reason.strip()
    if (
        latest is not None
        and latest.state_fingerprint == state["state_fingerprint"]
        and latest.state_version == state["state_version"]
        and latest.status == status.value
        and latest.reason == clean_reason
        and latest.reviewed_by_id == user_id
    ):
        return latest

    if latest is not None and not confirm_re_review:
        raise CostReviewConflictError(
            "A prior human cost-review disposition exists. Explicit re-review is required before changing or refreshing it."
        )

    decision_number = latest.decision_number + 1 if latest is not None else 1
    previous_hash = latest.decision_hash if latest is not None else None
    snapshot = state["snapshot"]
    decision_hash = _decision_hash(
        organization_id=organization_id,
        claim_id=claim.id,
        item_key=state["item_key"],
        state_fingerprint=state["state_fingerprint"],
        state_version=state["state_version"],
        decision_number=decision_number,
        status=status.value,
        reason=clean_reason,
        item_snapshot=snapshot,
        reviewed_by_id=user_id,
        previous_decision_hash=previous_hash,
    )
    decision = CostReviewDecision(
        organization_id=organization_id,
        claim_id=claim.id,
        item_key=state["item_key"],
        state_fingerprint=state["state_fingerprint"],
        state_version=state["state_version"],
        decision_number=decision_number,
        status=status.value,
        reason=clean_reason,
        item_snapshot=_jsonable(snapshot),
        reviewed_by_id=user_id,
        reviewed_at=datetime.now(UTC),
        previous_decision_hash=previous_hash,
        decision_hash=decision_hash,
    )
    db.add(decision)
    item.review_status = status
    db.flush()
    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="RECORD_COST_REVIEW_DECISION",
        entity_type="cost_item",
        entity_id=item.id,
        old_values={
            "prior_decision_hash": previous_hash,
            "decision_state": state["decision_state"],
        },
        new_values={
            "item_key": state["item_key"],
            "state_fingerprint": state["state_fingerprint"],
            "state_version": state["state_version"],
            "decision_number": decision_number,
            "status": status.value,
            "reason": clean_reason,
            "decision_hash": decision_hash,
            "confirm_re_review": confirm_re_review,
        },
        details=(
            "Recorded a human operational cost-review disposition against the exact current financial evidence "
            "state. This does not determine coverage, recoverability, reserve, settlement or payment."
        ),
    )
    return decision


def resolve_financial_flag(
    db: Session,
    *,
    claim: Claim,
    flag: FinancialFlag,
    status: FinancialFlagStatus,
    note: str,
    user_id: UUID,
):
    old = flag.status.value
    flag.status = status
    flag.resolution_note = note
    flag.resolved_by_id = user_id
    flag.resolved_at = datetime.now(UTC)
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user_id,
        action="RESOLVE_FINANCIAL_FLAG",
        entity_type="financial_flag",
        entity_id=flag.id,
        old_values={"status": old},
        new_values={"status": status.value, "note": note},
    )

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Iterable

from app.modules.rules.marine_registry import (
    MarineRuleDefinition,
    MarineRuleEvaluation,
    MarineRuleStatus,
)

MARINE_EXTENSION_VERSION = "12B.2.0"


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _rule(
    rule_id: str,
    family: str,
    topic: str,
    source_title: str,
    source_reference: str,
    prerequisites: tuple[str, ...],
    required_evidence: tuple[str, ...],
    candidate_implication: str,
    recommended_action: str,
    *,
    policy_context: str | None = None,
) -> MarineRuleDefinition:
    return MarineRuleDefinition(
        rule_id=rule_id,
        version="1.0.0",
        family=family,
        topic=topic,
        source_title=source_title,
        source_reference=source_reference,
        prerequisites=prerequisites,
        required_evidence=required_evidence,
        candidate_implication=candidate_implication,
        recommended_action=recommended_action,
        policy_context=policy_context,
    )


EXTENSION_RULES: tuple[MarineRuleDefinition, ...] = (
    _rule(
        "AAA-A4",
        "aaa_rules",
        "reasonable_repairs_and_repair_timing",
        "Association of Average Adjusters Rules of Practice",
        "A4",
        ("repair expenditure or repair deferment is indicated",),
        ("repair scope", "competitive quotation or reasonableness evidence", "repair timing/deferment evidence where relevant"),
        "Repair expenditure and timing may require A4 reasonableness review; the rule does not determine the allowable amount.",
        "Review competitive tenders or other reasonableness evidence, repair timing, Class constraints and any deferment basis before adjusting the repair cost.",
    ),
    _rule(
        "AAA-A5",
        "aaa_rules",
        "machinery_replacement_residual_value",
        "Association of Average Adjusters Rules of Practice",
        "A5",
        ("major machinery replacement or renewal is indicated",),
        ("replacement evidence", "damaged-part residual/sale/scrap value evidence"),
        "Replacement of a major machinery item may require residual-value review where the damaged item has a realistic sale or scrap value.",
        "Establish whether the damaged component is realistically saleable or has scrap/residual value and preserve the valuation or disposal evidence before final adjustment.",
    ),
    _rule(
        "HM-EVID-001",
        "hm_repairs",
        "maker_workshop_class_evidence",
        "MCRI H&M evidence completeness rule",
        "HM-EVID-001",
        ("machinery repair/replacement investigation is indicated",),
        ("workshop findings", "maker evidence where relevant", "Class attendance/approval where relevant"),
        "The technical evidence package may be incomplete for a defensible repairability, scope or causation review.",
        "Obtain and reconcile workshop findings, maker guidance and Class evidence that is relevant to the repair or approval pathway.",
    ),
    _rule(
        "HM-COST-001",
        "hm_repairs",
        "quotation_invoice_reasonableness",
        "MCRI H&M repair-cost review rule",
        "HM-COST-001",
        ("repair expenditure is recorded",),
        ("cost lines", "repair quotation", "final invoice when settlement-ready", "scope comparison"),
        "Recorded repair expenditure may require quotation, invoice and scope reasonableness review before adjustment.",
        "Reconcile quotations, invoices and repair scope; explain material variances and separate damage repairs from maintenance, upgrades or unrelated work.",
    ),
    _rule(
        "POLICY-WORDING-001",
        "policy_mia",
        "reviewed_policy_wording_available",
        "Reviewed policy / contract wording",
        "Policy wording availability",
        ("coverage or adjustment analysis requires actual wording",),
        ("human-approved policy/contract extraction",),
        "Generic marine rules must not substitute for the actual policy wording and governing law.",
        "Obtain and human-review the governing wording before any coverage, deductible, notice, due-diligence or total-loss conclusion.",
        policy_context="Actual policy wording and governing law control.",
    ),
    _rule(
        "POLICY-DEDUCTIBLE-001",
        "policy_mia",
        "deductible_or_excess",
        "Reviewed policy wording",
        "Deductible / excess",
        ("a reviewed deductible/excess term exists",),
        ("approved deductible/excess wording", "financial claim context"),
        "A reviewed deductible or excess term may affect the eventual adjustment but does not determine the payable amount by itself.",
        "Apply only the reviewed wording after classifying the claim and costs; document currency, amount, aggregation and any special machinery deductible terms.",
        policy_context="Actual policy wording controls.",
    ),
    _rule(
        "POLICY-NOTICE-001",
        "policy_mia",
        "notice_cooperation_time_requirements",
        "Reviewed policy wording",
        "Notice / cooperation / time requirements",
        ("a reviewed notice, cooperation or time-limit term exists",),
        ("approved term", "notification chronology", "relevant correspondence"),
        "A reviewed notice, cooperation or time requirement may require diarying or compliance review; no breach or prejudice is inferred.",
        "Compare the reviewed term with the actual chronology and correspondence, diary any deadline and escalate potential non-compliance for human coverage review.",
        policy_context="Actual policy wording and governing law control.",
    ),
    _rule(
        "POLICY-MACH-001",
        "policy_mia",
        "machinery_conditions_and_additional_perils",
        "Reviewed H&M policy wording",
        "Machinery conditions / Additional Perils",
        ("reviewed machinery-specific wording is present",),
        ("approved clause wording", "technical facts", "maintenance/workmanship evidence"),
        "Machinery-specific wording may affect the legal/coverage analysis, but the engine does not decide whether the clause is satisfied or responds.",
        "Review the exact clause language against the approved technical facts, due-diligence evidence and causation analysis before recording a coverage position.",
        policy_context="Actual policy wording and governing law control.",
    ),
    _rule(
        "GA-ABSORB-001",
        "general_average",
        "ga_absorption_wording",
        "Reviewed H&M policy wording / General Average framework",
        "General Average absorption",
        ("General Average is indicated",),
        ("approved GA/absorption wording", "GA declaration/context", "insured property contribution context"),
        "A General Average absorption provision may change the handling workflow, but the engine does not determine whether absorption applies or calculate an adjustment.",
        "Review the exact absorption wording, limits and conditions and preserve the underlying GA evidence before deciding whether to pursue contributions or absorb the loss.",
        policy_context="Actual policy wording controls; no automated GA adjustment is performed.",
    ),
    _rule(
        "CP-WORDING-001",
        "charterparty",
        "reviewed_charterparty_allocation_wording",
        "Reviewed charterparty / contractual wording",
        "Charterparty wording availability",
        ("charterparty allocation or recovery context is indicated",),
        ("human-approved charterparty term", "operational facts", "cost evidence"),
        "Only reviewed charterparty wording can support an allocation or recovery lead; missing terms must not be inferred.",
        "Review the actual off-hire, bunkers, deviation, repair, indemnity or war-risk wording relevant to the factual trigger before recording an allocation position.",
    ),
)

EXTENSION_RULE_BY_ID = {rule.rule_id: rule for rule in EXTENSION_RULES}


def extension_registry_hash() -> str:
    return _hash([{"definition": asdict(rule), "hash": rule.definition_hash} for rule in EXTENSION_RULES])


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict) and "value" in value:
        return str(value.get("value") or "")
    return str(value)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return bool(value)
    return _text(value).strip().lower() in {"true", "yes", "y", "1", "required", "temporary", "declared"}


def _fact_source(row: Any) -> dict[str, Any]:
    return {
        "kind": "claim_fact",
        "id": str(row.id),
        "field_path": row.field_path,
        "value": row.value,
        "document_id": str(row.source_document_id),
        "extraction_id": str(row.source_extraction_id),
        "version": row.version,
    }


def _cost_source(row: Any) -> dict[str, Any]:
    return {
        "kind": "cost_item",
        "id": str(row.id),
        "document_id": str(row.document_id),
        "description": row.description,
        "category": row.category,
        "amount": str(row.amount),
        "currency": row.currency,
        "review_status": row.review_status.value,
    }


def _document_source(row: Any) -> dict[str, Any]:
    return {
        "kind": "document",
        "id": str(row.id),
        "document_type": row.document_type,
        "version": row.version_number,
    }


def _policy_term_source(term: Any) -> dict[str, Any]:
    return {
        "kind": "policy_term",
        "id": str(term.extraction_id),
        "category": term.category,
        "value": term.value,
        "document_id": str(term.source.document_id),
        "document_version": term.source.document_version,
        "document_type": term.source.document_type,
        "locator": term.source.locator,
    }


def _evaluation(
    definition: MarineRuleDefinition,
    status: MarineRuleStatus,
    evidence: Iterable[dict[str, Any]],
    missing: Iterable[str],
    rationale: str,
) -> MarineRuleEvaluation:
    evidence_tuple = tuple(evidence)
    missing_tuple = tuple(missing)
    payload = {
        "rule_id": definition.rule_id,
        "rule_version": definition.version,
        "definition_hash": definition.definition_hash,
        "status": status.value,
        "evidence_used": evidence_tuple,
        "missing_prerequisites": missing_tuple,
        "rationale": rationale,
        "candidate_implication": definition.candidate_implication,
        "recommended_action": definition.recommended_action,
    }
    return MarineRuleEvaluation(
        rule_id=definition.rule_id,
        rule_version=definition.version,
        definition_hash=definition.definition_hash,
        family=definition.family,
        topic=definition.topic,
        source_title=definition.source_title,
        source_reference=definition.source_reference,
        status=status,
        evidence_used=evidence_tuple,
        missing_prerequisites=missing_tuple,
        rationale=rationale,
        candidate_implication=definition.candidate_implication,
        recommended_action=definition.recommended_action,
        evaluation_hash=_hash(payload),
    )


def evaluate_extension_rules(
    *,
    claim: Any,
    fact_rows: Iterable[Any],
    documents: Iterable[Any],
    costs: Iterable[Any],
    policy: Any,
) -> tuple[MarineRuleEvaluation, ...]:
    fact_rows = tuple(fact_rows)
    documents = tuple(documents)
    costs = tuple(costs)
    terms = tuple(getattr(policy, "terms", ()) or ())
    fact_by_path = {row.field_path: row for row in fact_rows}
    facts = {path: row.value for path, row in fact_by_path.items()}
    doc_by_type: dict[str, list[Any]] = {}
    for row in documents:
        doc_by_type.setdefault(row.document_type or "", []).append(row)

    def fact(path: str) -> Any:
        return facts.get(path)

    def fact_evidence(*paths: str) -> list[dict[str, Any]]:
        return [_fact_source(fact_by_path[path]) for path in paths if path in fact_by_path]

    def docs(*types: str) -> list[Any]:
        output: list[Any] = []
        for document_type in types:
            output.extend(doc_by_type.get(document_type, []))
        return output

    def document_evidence(*types: str) -> list[dict[str, Any]]:
        return [_document_source(row) for row in docs(*types)]

    def cost_matches(*needles: str) -> list[Any]:
        return [
            row for row in costs
            if any(needle in f"{row.description} {row.category or ''}".lower() for needle in needles)
        ]

    def policy_terms(*categories: str) -> list[Any]:
        wanted = set(categories)
        return [term for term in terms if term.category in wanted]

    def matching_policy_terms(*needles: str) -> list[Any]:
        return [
            term for term in terms
            if any(needle in f"{term.category} {term.value}".lower() for needle in needles)
        ]

    evaluations: list[MarineRuleEvaluation] = []
    repair_costs = tuple(costs)
    quotation_docs = docs("quotation")
    invoice_docs = docs("final_invoice")
    workshop_docs = docs("workshop_report")
    class_docs = docs("class_report")
    maker_docs = docs("maker_recommendation")
    replacement_costs = cost_matches("replace", "replacement", "renew", "renewal", "new unit", "new turbo")
    replacement_signal = _truthy(fact("repair.replacement")) or bool(replacement_costs)

    rule = EXTENSION_RULE_BY_ID["AAA-A4"]
    deferment_signal = _truthy(fact("repair.deferred")) or "defer" in _text(fact("repair.timing")).lower()
    a4_evidence = (
        [_cost_source(row) for row in repair_costs]
        + document_evidence("quotation", "final_invoice")
        + fact_evidence("repair.deferred", "repair.timing", "repair.deferment_basis", "repair.class_recommendation_expiry")
    )
    if not repair_costs and not deferment_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, a4_evidence, (), "No recorded repair expenditure or repair-deferment signal is present."))
    else:
        missing: list[str] = []
        if repair_costs and not quotation_docs:
            missing.append("competitive quotation or documented repair-cost reasonableness evidence")
        if deferment_signal and fact("repair.deferment_basis") is None:
            missing.append("reviewed repair-deferment basis")
        if deferment_signal and fact("repair.class_recommendation_expiry") is None:
            missing.append("Class timing/recommendation evidence relevant to deferment")
        status = MarineRuleStatus.INSUFFICIENT_EVIDENCE if missing else MarineRuleStatus.TRIGGERED
        rationale = "Repair expenditure/deferment is indicated, but the evidence package is incomplete for A4 reasonableness review." if missing else "Repair expenditure/deferment and supporting reasonableness/timing evidence are present for human A4 review."
        evaluations.append(_evaluation(rule, status, a4_evidence, missing, rationale))

    rule = EXTENSION_RULE_BY_ID["AAA-A5"]
    a5_evidence = (
        fact_evidence("repair.replacement", "repair.residual_value", "repair.scrap_value", "repair.damaged_part_saleable")
        + [_cost_source(row) for row in replacement_costs]
    )
    if not replacement_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, a5_evidence, (), "No major machinery replacement or renewal signal is present."))
    elif all(fact(path) is None for path in ("repair.residual_value", "repair.scrap_value", "repair.damaged_part_saleable")):
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, a5_evidence, ("damaged-part residual/sale/scrap value evidence",), "Replacement is indicated, but no controlled residual-value or saleability evidence is available."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, a5_evidence, (), "Replacement is indicated and controlled residual-value/saleability evidence is available for human A5 review."))

    rule = EXTENSION_RULE_BY_ID["HM-EVID-001"]
    machinery_signal = replacement_signal or _truthy(fact("repair.temporary")) or any(token in (claim.incident_description or "").lower() for token in ("engine", "turbo", "machinery"))
    tech_evidence = document_evidence("workshop_report", "maker_recommendation", "class_report")
    if not machinery_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, tech_evidence, (), "No machinery repair/replacement investigation signal is present."))
    else:
        missing = []
        if not workshop_docs:
            missing.append("workshop findings")
        if replacement_signal and not maker_docs and fact("repair.replacement_reason") is None:
            missing.append("maker guidance or reviewed replacement rationale")
        class_expected = _truthy(fact("class.attended")) or _truthy(fact("class.approval_required"))
        if class_expected and not class_docs:
            missing.append("Class attendance/approval evidence")
        evaluations.append(_evaluation(
            rule,
            MarineRuleStatus.INSUFFICIENT_EVIDENCE if missing else MarineRuleStatus.TRIGGERED,
            tech_evidence + fact_evidence("class.attended", "class.approval_required", "repair.replacement_reason"),
            missing,
            "The machinery evidence package is incomplete for defensible technical review." if missing else "Workshop and other currently-required technical evidence are available for human review.",
        ))

    rule = EXTENSION_RULE_BY_ID["HM-COST-001"]
    cost_evidence = [_cost_source(row) for row in repair_costs] + document_evidence("quotation", "final_invoice")
    if not repair_costs:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, cost_evidence, (), "No repair expenditure is recorded."))
    else:
        missing = []
        if not quotation_docs:
            missing.append("repair quotation")
        status_value = getattr(claim.status, "value", str(claim.status))
        if status_value in {"settlement", "closed"} and not invoice_docs:
            missing.append("final repair invoice")
        evaluations.append(_evaluation(
            rule,
            MarineRuleStatus.INSUFFICIENT_EVIDENCE if missing else MarineRuleStatus.TRIGGERED,
            cost_evidence,
            missing,
            "Repair costs are recorded, but quotation/invoice evidence is incomplete for reasonableness review." if missing else "Repair costs and the currently-required quotation/invoice evidence are available for human reasonableness review.",
        ))

    rule = EXTENSION_RULE_BY_ID["POLICY-WORDING-001"]
    policy_evidence = [_policy_term_source(term) for term in terms]
    if not terms:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, (), ("human-approved policy/contract wording",), "No approved current policy/contract extraction is available to govern generic marine-rule analysis."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_TRIGGERED, policy_evidence[:12], (), "Approved current policy/contract wording is available; downstream rule prompts remain subordinate to that wording."))

    rule = EXTENSION_RULE_BY_ID["POLICY-DEDUCTIBLE-001"]
    deductible_terms = policy_terms("deductible")
    if not terms:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, (), ("reviewed policy wording",), "Deductible review cannot be performed without approved policy wording."))
    elif not deductible_terms:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, policy_evidence[:6], (), "No approved deductible/excess term is present in the current reviewed policy intelligence."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, [_policy_term_source(term) for term in deductible_terms], (), "Approved deductible/excess wording is present and should be applied only after human classification of the claim and costs."))

    rule = EXTENSION_RULE_BY_ID["POLICY-NOTICE-001"]
    notice_terms = policy_terms("notice", "time_limit")
    if not terms:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, (), ("reviewed policy wording",), "Notice/time requirements cannot be reviewed without approved policy wording."))
    elif not notice_terms:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, policy_evidence[:6], (), "No approved notice/time-limit term is present in current policy intelligence."))
    else:
        evidence = [_policy_term_source(term) for term in notice_terms] + [{"kind": "claim", "id": str(claim.id), "field": "notification_date", "value": claim.notification_date.isoformat()}]
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Approved notice/time-limit wording is present; compliance and any deadline require human chronology review."))

    rule = EXTENSION_RULE_BY_ID["POLICY-MACH-001"]
    machinery_terms = matching_policy_terms("additional perils", "machinery", "due diligence", "workmanship", "latent defect")
    if not terms:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, (), ("reviewed H&M policy wording",), "Machinery-specific clause review cannot be performed without approved wording."))
    elif not machinery_terms:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, policy_evidence[:6], (), "No machinery-specific or Additional-Perils-style wording is identified in the approved policy intelligence."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, [_policy_term_source(term) for term in machinery_terms], (), "Approved machinery-specific wording is present and requires human application to the technical facts."))

    rule = EXTENSION_RULE_BY_ID["GA-ABSORB-001"]
    ga_signal = _truthy(fact("ga.declared")) or "general average" in (claim.incident_description or "").lower() or bool(policy_terms("general_average"))
    absorption_terms = matching_policy_terms("absorption", "absorb")
    ga_evidence = fact_evidence("ga.declared") + [_policy_term_source(term) for term in policy_terms("general_average")]
    if not ga_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, ga_evidence, (), "No General Average signal is present in the current controlled evidence."))
    elif not terms:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, ga_evidence, ("reviewed policy wording for GA/absorption",), "General Average is indicated, but no approved policy wording is available to assess an absorption workflow."))
    elif absorption_terms:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, ga_evidence + [_policy_term_source(term) for term in absorption_terms], (), "General Average is indicated and approved absorption-related wording is present for human limits/conditions review."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, ga_evidence, (), "General Average is indicated, but no absorption wording is identified in the current approved policy intelligence."))

    rule = EXTENSION_RULE_BY_ID["CP-WORDING-001"]
    charter_docs = docs("charter_party", "contract")
    charter_terms = [term for term in terms if term.source.document_type in {"charter_party", "contract"} or term.category == "charterparty_incorporation"]
    allocation_signal = bool(charter_docs) or bool(charter_terms) or any(token in (claim.incident_description or "").lower() for token in ("charter", "off-hire", "off hire"))
    evidence = document_evidence("charter_party", "contract") + [_policy_term_source(term) for term in charter_terms]
    if not allocation_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No charterparty allocation/recovery context is indicated."))
    elif not charter_terms:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("human-approved relevant charterparty wording",), "A charterparty/contract context is indicated, but no relevant approved clause extraction is available; terms are not inferred."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Relevant reviewed charterparty/contract wording is available for human allocation/recovery analysis."))

    return tuple(evaluations)

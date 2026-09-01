from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterable

MARINE_REGISTRY_VERSION = "12B.1.0"


class MarineRuleStatus(str, Enum):
    TRIGGERED = "triggered"
    NOT_TRIGGERED = "not_triggered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class MarineRuleDefinition:
    rule_id: str
    version: str
    family: str
    topic: str
    source_title: str
    source_reference: str
    prerequisites: tuple[str, ...]
    required_evidence: tuple[str, ...]
    candidate_implication: str
    recommended_action: str
    jurisdiction: str | None = None
    policy_context: str | None = None

    @property
    def definition_hash(self) -> str:
        return _hash(asdict(self))


@dataclass(frozen=True)
class MarineRuleEvaluation:
    rule_id: str
    rule_version: str
    definition_hash: str
    family: str
    topic: str
    source_title: str
    source_reference: str
    status: MarineRuleStatus
    evidence_used: tuple[dict[str, Any], ...]
    missing_prerequisites: tuple[str, ...]
    rationale: str
    candidate_implication: str
    recommended_action: str
    evaluation_hash: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["evidence_used"] = list(self.evidence_used)
        payload["missing_prerequisites"] = list(self.missing_prerequisites)
        return payload


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
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
    version: str = "1.0.0",
    jurisdiction: str | None = None,
    policy_context: str | None = None,
) -> MarineRuleDefinition:
    return MarineRuleDefinition(
        rule_id=rule_id,
        version=version,
        family=family,
        topic=topic,
        source_title=source_title,
        source_reference=source_reference,
        prerequisites=prerequisites,
        required_evidence=required_evidence,
        candidate_implication=candidate_implication,
        recommended_action=recommended_action,
        jurisdiction=jurisdiction,
        policy_context=policy_context,
    )


MARINE_RULES: tuple[MarineRuleDefinition, ...] = (
    _rule(
        "TECH-001", "hm_machinery", "running_hours_and_overhaul_interval", "MCRI H&M machinery review rule", "TECH-001",
        ("reviewed running hours since overhaul", "reviewed recommended overhaul interval"),
        ("approved maintenance facts",),
        "The maintenance interval may require investigation as a possible contributing context; this is not a causation finding.",
        "Review PMS, running-hours history, maker guidance and technical causation evidence before forming any causation view.",
    ),
    _rule(
        "TECH-002", "hm_machinery", "recent_overhaul_workmanship", "MCRI H&M machinery review rule", "TECH-002",
        ("reviewed last overhaul date", "incident date"), ("approved overhaul date", "incident record"),
        "A failure soon after overhaul may justify workmanship, assembly, replaced-part and recovery investigation.",
        "Obtain the overhaul scope, workshop records, replaced-part details and post-overhaul testing evidence.",
    ),
    _rule(
        "TECH-003", "hm_machinery", "deferred_maintenance", "MCRI H&M machinery review rule", "TECH-003",
        ("reviewed PMS or deferral evidence",), ("approved PMS facts",),
        "Deferred maintenance may require technical relevance review; it does not establish causation or policy breach.",
        "Review the deferral basis, approval, risk assessment and technical relationship to the casualty.",
    ),
    _rule(
        "TECH-006", "hm_repairs", "temporary_vs_permanent_repair", "MCRI H&M repair review rule", "TECH-006",
        ("reviewed temporary-repair indicator",), ("temporary repair specification or approved fact",),
        "A temporary repair may leave an outstanding permanent-repair, class-condition or cost-classification question.",
        "Confirm class conditions, expiry, permanent repair scope and the relationship between temporary and permanent work.",
    ),
    _rule(
        "HM-REPAIR-001", "hm_repairs", "repair_vs_replacement", "MCRI H&M repair-cost review rule", "HM-REPAIR-001",
        ("replacement or renewal is proposed/claimed",), ("workshop findings", "repairability evidence", "replacement rationale"),
        "Replacement expenditure may require a repairability, betterment and scope reasonableness review.",
        "Compare repair and replacement evidence, maker/workshop findings, quotations and any residual-value or betterment considerations.",
    ),
    _rule(
        "AAA-D1", "aaa_rules", "removal_or_movement_to_repairs", "Association of Average Adjusters Rules of Practice", "D1",
        ("movement/removal expenditure is claimed", "movement is linked by reviewed evidence to a place of repair"),
        ("cost line", "towage/movement purpose", "repair destination or necessity evidence"),
        "The expenditure may require D1 treatment review; the rule hit does not decide recoverability.",
        "Verify why the vessel/property was moved, the repair destination, necessity, invoices/contracts and the applicable policy/adjusting basis.",
    ),
    _rule(
        "AAA-D2", "aaa_rules", "fuel_and_stores_during_repairs", "Association of Average Adjusters Rules of Practice", "D2",
        ("fuel or stores expenditure is claimed", "reviewed evidence links consumption to qualifying repair activity"),
        ("cost line", "repair-activity consumption evidence"),
        "Fuel or stores may require D2 treatment review if consumed for qualifying repair activity rather than ordinary operation.",
        "Separate repair-related consumption from voyage, STS, cargo, standby or ordinary operational consumption and preserve the supporting logs/invoices.",
    ),
    _rule(
        "AAA-D6", "aaa_rules", "machinery_assisting_repairs", "Association of Average Adjusters Rules of Practice", "D6",
        ("machinery-use expenditure is claimed", "reviewed evidence shows machinery was used to assist repairs"),
        ("cost line", "machinery-use purpose", "repair activity evidence"),
        "Machinery use may require D6 treatment review when it specifically assisted repair work.",
        "Verify which machinery was used, when, for what repair activity, and the evidenced incremental consumption or cost.",
    ),
    _rule(
        "AAA-D8", "aaa_rules", "scraping_and_painting", "Association of Average Adjusters Rules of Practice", "D8",
        ("surface preparation or painting expenditure is claimed",), ("cost line", "damage/repair relationship evidence"),
        "Surface-treatment costs may require D8 allocation review depending on their relationship to insured repairs and ordinary maintenance.",
        "Separate damage-related preparation/painting from routine coating or maintenance and verify the repair specification and invoice allocation.",
    ),
    _rule(
        "AAA-D9", "aaa_rules", "temporary_generator", "Association of Average Adjusters Rules of Practice", "D9",
        ("temporary generator use is indicated",), ("temporary-generator purpose", "duration", "cost/consumption evidence"),
        "Temporary generator expenditure may require D9 treatment review depending on why and how it supported repairs.",
        "Confirm purpose, period of use, repair dependency, hire/fuel costs and any ordinary operational element.",
    ),
    _rule(
        "AAA-D10", "aaa_rules", "liner_vessel_considerations", "Association of Average Adjusters Rules of Practice", "D10",
        ("the vessel operates in a liner-service context",), ("reviewed service-type evidence", "relevant repair/cost facts"),
        "A liner-service context may require D10 review where the rule is relevant to the claimed repair circumstances.",
        "Confirm the vessel's service pattern and identify the specific repair/cost question before applying any D10 interpretation.",
    ),
    _rule(
        "MIA-S78", "policy_mia", "sue_and_labour", "Marine Insurance Act 1906", "Section 78",
        ("mitigation/protective expenditure is indicated", "applicable policy wording has been reviewed"),
        ("policy wording", "purpose and necessity evidence", "cost evidence"),
        "The expenditure may justify Sue & Labour review, but the engine does not decide whether it is covered or recoverable.",
        "Review the actual policy wording, insured peril context, purpose, reasonableness, causation and overlap with salvage or General Average.",
        jurisdiction="England and Wales where applicable", policy_context="Actual policy wording and governing law control.",
    ),
    _rule(
        "MARINE-EMERGENCY-001", "emergency_services", "salvage_towage_sue_labour_ga_classification", "MCRI marine emergency-services classification rule", "MARINE-EMERGENCY-001",
        ("towage, salvage or emergency-service activity is indicated",),
        ("service contract/award basis", "danger/emergency evidence", "purpose", "GA/Sue & Labour context"),
        "The service may require classification between salvage, contractual towage, Sue & Labour, General Average or ordinary operational expenditure.",
        "Obtain the service contract or award basis, casualty/emergency evidence, purpose, invoices and relevant policy/GA documents before classification.",
    ),
    _rule(
        "GA-YAR-001", "general_average", "ga_declaration_and_yar_incorporation", "York-Antwerp Rules / contractual GA framework", "GA/YAR incorporation review",
        ("GA declaration or GA-type extraordinary expenditure is indicated",),
        ("GA declaration", "contractual YAR incorporation/edition", "common-adventure facts", "expenditure evidence"),
        "The circumstances may justify General Average issue spotting; no contribution liability or adjustment is determined.",
        "Confirm whether GA was declared, the incorporated YAR edition, common-adventure/common-safety facts, securities and the exact expenditure classification question.",
    ),
    _rule(
        "POLICY-TL-001", "policy_mia", "atl_ctl_prerequisites", "Policy wording / Marine Insurance Act framework", "ATL/CTL review prerequisites",
        ("actual or constructive total-loss review is indicated",),
        ("insured value", "repair/recovery estimate", "salvage/residual values", "policy wording", "location/recovery facts"),
        "The facts may justify ATL/CTL analysis, but the engine does not determine total-loss status.",
        "Obtain the governing wording and complete repair, recovery, residual-value and location evidence before any total-loss conclusion.",
        policy_context="Actual policy wording and governing law control.",
    ),
    _rule(
        "CP-COST-001", "charterparty", "contractual_cost_allocation", "Reviewed charterparty / contractual wording", "Cost-allocation review",
        ("a charterparty/contract is present", "a relevant cost-allocation question exists"),
        ("reviewed contractual clause", "cost evidence", "operational facts"),
        "A reviewed contractual term may create an allocation or later recovery question; no indemnity or liability is inferred.",
        "Identify and review the actual clause, parties, factual trigger and claimed cost before recording any allocation or recovery position.",
    ),
)

RULE_BY_ID = {rule.rule_id: rule for rule in MARINE_RULES}


def registry_hash() -> str:
    return _hash([{"definition": asdict(rule), "hash": rule.definition_hash} for rule in MARINE_RULES])


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


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, str):
        value = value.lower().replace(",", "").replace("hours", "").replace("hrs", "").strip()
    try:
        return Decimal(str(value)) if value is not None else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _date_value(value: Any) -> date | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value is not None else None
    except (TypeError, ValueError):
        return None


def _fact_source(row: Any) -> dict[str, Any]:
    return {
        "kind": "claim_fact",
        "id": str(row.id),
        "field_path": row.field_path,
        "value": _jsonable(row.value),
        "document_id": str(row.source_document_id),
        "extraction_id": str(row.source_extraction_id),
        "segment_id": str(row.source_segment_id) if row.source_segment_id else None,
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
    return {"kind": "document", "id": str(row.id), "document_type": row.document_type, "version": row.version_number}


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


def evaluate_marine_rules(
    *,
    claim: Any,
    fact_rows: Iterable[Any],
    documents: Iterable[Any],
    costs: Iterable[Any],
) -> tuple[MarineRuleEvaluation, ...]:
    fact_rows = tuple(fact_rows)
    documents = tuple(documents)
    costs = tuple(costs)
    fact_by_path = {row.field_path: row for row in fact_rows}
    facts = {path: row.value for path, row in fact_by_path.items()}
    doc_by_type: dict[str, list[Any]] = {}
    for row in documents:
        doc_by_type.setdefault(row.document_type or "", []).append(row)

    def fact(path: str) -> Any:
        return facts.get(path)

    def fact_evidence(*paths: str) -> list[dict[str, Any]]:
        return [_fact_source(fact_by_path[path]) for path in paths if path in fact_by_path]

    def cost_matches(*needles: str) -> list[Any]:
        output = []
        for row in costs:
            text = f"{row.description} {row.category or ''}".lower()
            if any(needle in text for needle in needles):
                output.append(row)
        return output

    def document_evidence(*types: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for document_type in types:
            output.extend(_document_source(row) for row in doc_by_type.get(document_type, []))
        return output

    evaluations: list[MarineRuleEvaluation] = []

    rule = RULE_BY_ID["TECH-001"]
    hours = _decimal(fact("maintenance.running_hours_since_overhaul"))
    interval = _decimal(fact("maintenance.recommended_overhaul_interval"))
    evidence = fact_evidence("maintenance.running_hours_since_overhaul", "maintenance.recommended_overhaul_interval")
    if hours is None or interval is None or interval <= 0:
        missing = []
        if hours is None:
            missing.append("reviewed running hours since overhaul")
        if interval is None or interval <= 0:
            missing.append("reviewed recommended overhaul interval")
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, missing, "The maintenance comparison cannot be completed from the current approved evidence."))
    elif hours > interval:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), f"Reviewed running hours ({hours} h) exceed the reviewed interval ({interval} h); technical significance remains for human investigation."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_TRIGGERED, evidence, (), f"Reviewed running hours ({hours} h) do not exceed the reviewed interval ({interval} h)."))

    rule = RULE_BY_ID["TECH-002"]
    overhaul_date = _date_value(fact("maintenance.last_overhaul_date"))
    evidence = fact_evidence("maintenance.last_overhaul_date") + [{"kind": "claim", "id": str(claim.id), "field": "incident_date", "value": claim.incident_date.isoformat()}]
    if overhaul_date is None:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("reviewed last overhaul date",), "The interval between overhaul and casualty cannot be evaluated."))
    elif overhaul_date > claim.incident_date:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("resolve overhaul-date chronology",), "The reviewed overhaul date is after the incident date and requires chronology review."))
    else:
        days = (claim.incident_date - overhaul_date).days
        status = MarineRuleStatus.TRIGGERED if days <= 90 else MarineRuleStatus.NOT_TRIGGERED
        evaluations.append(_evaluation(rule, status, evidence, (), f"The casualty occurred {days} days after the reviewed overhaul date; the 90-day recent-overhaul review threshold {'is' if days <= 90 else 'is not'} met."))

    rule = RULE_BY_ID["TECH-003"]
    deferred = _truthy(fact("maintenance.overhaul_deferred")) or "defer" in _text(fact("maintenance.pms_status")).lower()
    evidence = fact_evidence("maintenance.overhaul_deferred", "maintenance.pms_status")
    if not evidence:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, (), ("reviewed PMS or deferral evidence",), "No approved PMS/deferral fact is available to evaluate this rule."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED if deferred else MarineRuleStatus.NOT_TRIGGERED, evidence, (), "Reviewed PMS/deferral evidence indicates deferred maintenance." if deferred else "Current reviewed PMS/deferral evidence does not indicate deferred maintenance."))

    rule = RULE_BY_ID["TECH-006"]
    temporary = _truthy(fact("repair.temporary")) or _truthy(fact("temporary_repair"))
    evidence = fact_evidence("repair.temporary", "temporary_repair")
    if temporary:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Reviewed facts indicate a temporary repair and therefore a permanent-repair/class follow-up question."))
    elif evidence:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_TRIGGERED, evidence, (), "Reviewed facts do not indicate a temporary repair."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, (), (), "No temporary-repair signal is present in the current controlled evidence."))

    rule = RULE_BY_ID["HM-REPAIR-001"]
    replacement_costs = cost_matches("replace", "replacement", "renew", "renewal", "new unit", "new turbo")
    replacement_signal = _truthy(fact("repair.replacement")) or bool(replacement_costs)
    evidence = fact_evidence("repair.replacement", "repair.replacement_reason", "repair.repairability") + [_cost_source(row) for row in replacement_costs]
    if not replacement_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No replacement/renewal signal is present."))
    elif fact("repair.replacement_reason") is None and fact("repair.repairability") is None:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("reviewed repairability or replacement rationale",), "Replacement is indicated, but the controlled evidence does not yet explain why repair was unsuitable or unreasonable."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Replacement is indicated and a reviewed repairability/replacement rationale is available for human scope and betterment review."))

    rule = RULE_BY_ID["AAA-D1"]
    d1_costs = cost_matches("tow", "tug", "pilot", "deviation", "port charge", "movement")
    towage_signal = _truthy(fact("operational_impact.towage")) or bool(d1_costs)
    repair_purpose = _truthy(fact("operational_impact.moved_for_repairs")) or "repair" in _text(fact("towage.purpose")).lower() or fact("repair.location") is not None or fact("repair.destination") is not None
    evidence = fact_evidence("operational_impact.towage", "operational_impact.moved_for_repairs", "towage.purpose", "repair.location", "repair.destination") + [_cost_source(row) for row in d1_costs]
    if not towage_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No movement/removal expenditure or towage signal is present."))
    elif not d1_costs or not repair_purpose:
        missing = []
        if not d1_costs:
            missing.append("movement/removal cost evidence")
        if not repair_purpose:
            missing.append("reviewed evidence linking movement to a repair place/purpose")
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, missing, "Movement/towage is indicated, but D1 prerequisites are not fully evidenced."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Movement expenditure and reviewed repair-purpose/location evidence are both present; D1 treatment should be reviewed by the handler/adjuster."))

    rule = RULE_BY_ID["AAA-D2"]
    d2_costs = cost_matches("fuel", "bunker", "stores")
    evidence = fact_evidence("repair.fuel_consumed", "repair.fuel_consumption_purpose") + [_cost_source(row) for row in d2_costs]
    repair_fuel = _truthy(fact("repair.fuel_consumed")) or "repair" in _text(fact("repair.fuel_consumption_purpose")).lower()
    if not d2_costs:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No fuel/stores cost line is present."))
    elif repair_fuel:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Fuel/stores expenditure is present and approved evidence links consumption to repair activity; D2 allocation remains a human adjusting review."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("reviewed repair-activity consumption purpose",), "Fuel/stores expenditure alone is insufficient to distinguish repair consumption from STS, voyage, standby or ordinary operational use."))

    rule = RULE_BY_ID["AAA-D6"]
    d6_costs = cost_matches("winch", "machinery", "generator", "engine", "crane", "power")
    assist = _truthy(fact("repair.machinery_assisted")) or "repair" in _text(fact("repair.machinery_assistance_purpose")).lower()
    evidence = fact_evidence("repair.machinery_assisted", "repair.machinery_assistance_purpose") + [_cost_source(row) for row in d6_costs]
    if not d6_costs and not assist:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No machinery-assisting-repairs signal is present."))
    elif not d6_costs or not assist:
        missing = []
        if not d6_costs:
            missing.append("machinery-use cost/consumption evidence")
        if not assist:
            missing.append("reviewed evidence that machinery specifically assisted repairs")
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, missing, "Machinery use or related expenditure is indicated, but the repair-assistance link is incomplete."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Machinery-use expenditure and reviewed repair-assistance evidence are both present; D6 treatment should be reviewed."))

    rule = RULE_BY_ID["AAA-D8"]
    d8_costs = cost_matches("paint", "painting", "scrap", "scraping", "coat", "coating", "surface preparation")
    related = _truthy(fact("repair.surface_treatment_damage_related")) or "damage" in _text(fact("repair.surface_treatment_purpose")).lower()
    evidence = fact_evidence("repair.surface_treatment_damage_related", "repair.surface_treatment_purpose") + [_cost_source(row) for row in d8_costs]
    if not d8_costs:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No surface-treatment cost line is present."))
    elif related:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Surface-treatment expenditure and reviewed damage/repair relationship evidence are present; D8 allocation should be reviewed."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("reviewed damage/repair relationship for surface treatment",), "Surface-treatment expenditure is present, but its relationship to casualty repairs versus routine maintenance is unresolved."))

    rule = RULE_BY_ID["AAA-D9"]
    d9_costs = cost_matches("temporary generator", "hire generator", "rental generator")
    temp_generator = _truthy(fact("repair.temporary_generator"))
    evidence = fact_evidence("repair.temporary_generator", "repair.temporary_generator_purpose", "repair.temporary_generator_duration") + [_cost_source(row) for row in d9_costs]
    if not d9_costs and not temp_generator:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No temporary-generator signal is present."))
    elif not temp_generator or fact("repair.temporary_generator_purpose") is None:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("reviewed temporary-generator purpose",), "Temporary-generator use/cost is indicated, but its purpose and repair dependency are not fully evidenced."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Reviewed evidence confirms temporary-generator use and purpose; D9 treatment should be reviewed without assuming recoverability."))

    rule = RULE_BY_ID["AAA-D10"]
    service_type = _text(fact("vessel.service_type")).lower()
    evidence = fact_evidence("vessel.service_type")
    if not service_type:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("reviewed vessel service type",), "The vessel's liner/non-liner service context is not recorded in approved facts."))
    elif "liner" in service_type:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Reviewed service-type evidence indicates a liner context; any D10 relevance must be tied to a specific repair/cost question."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "Reviewed service-type evidence does not indicate a liner-service context."))

    rule = RULE_BY_ID["MIA-S78"]
    mitigation_costs = cost_matches("protect", "mitigat", "emergency", "tow", "salvage", "preserve", "safeguard")
    mitigation_signal = _truthy(fact("sue_and_labour.claimed")) or bool(mitigation_costs)
    policy_docs = doc_by_type.get("policy", [])
    purpose = _text(fact("sue_and_labour.purpose")).lower()
    evidence = fact_evidence("sue_and_labour.claimed", "sue_and_labour.purpose") + [_cost_source(row) for row in mitigation_costs] + document_evidence("policy")
    if not mitigation_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No mitigation/protective expenditure signal is present."))
    elif not policy_docs or not purpose:
        missing = []
        if not policy_docs:
            missing.append("applicable policy wording")
        if not purpose:
            missing.append("reviewed purpose/necessity of the expenditure")
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, missing, "Protective/mitigation expenditure is indicated, but Sue & Labour review prerequisites are incomplete."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Protective/mitigation expenditure, reviewed purpose and policy document are present; Section 78/Sue & Labour treatment requires human policy analysis."))

    rule = RULE_BY_ID["MARINE-EMERGENCY-001"]
    emergency_costs = cost_matches("tow", "tug", "salvage", "emergency")
    emergency_signal = _truthy(fact("operational_impact.towage")) or _truthy(fact("salvage.service")) or bool(emergency_costs)
    basis_paths = ("emergency_service.contract_type", "salvage.award_basis", "towage.contractual_basis", "general_average.declared", "sue_and_labour.claimed")
    evidence = fact_evidence("operational_impact.towage", "salvage.service", *basis_paths) + [_cost_source(row) for row in emergency_costs]
    if not emergency_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No towage/salvage/emergency-service signal is present."))
    elif not any(fact(path) is not None for path in basis_paths):
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("service contract/award or classification-basis evidence",), "Emergency service is indicated, but the evidence is insufficient to distinguish salvage, contractual towage, Sue & Labour, GA or ordinary expenditure."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Emergency-service activity and at least one reviewed classification-basis fact are present; final classification remains a human decision."))

    rule = RULE_BY_ID["GA-YAR-001"]
    ga_costs = cost_matches("general average", "port of refuge", "deviation", "sts", "tow", "tug")
    ga_signal = _truthy(fact("general_average.declared")) or bool(ga_costs)
    yar = fact("general_average.yar_edition") or fact("general_average.contractual_incorporation")
    evidence = fact_evidence("general_average.declared", "general_average.yar_edition", "general_average.contractual_incorporation") + [_cost_source(row) for row in ga_costs]
    if not ga_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No GA declaration or GA-type extraordinary expenditure signal is present."))
    elif yar is None:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("reviewed YAR incorporation/edition",), "GA or GA-type expenditure is indicated, but the contractual YAR framework is not yet evidenced."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "GA/GA-type expenditure and reviewed YAR incorporation/edition evidence are present; classification and contribution remain for human adjustment."))

    rule = RULE_BY_ID["POLICY-TL-001"]
    tl_signal = _truthy(fact("total_loss.claimed")) or _truthy(fact("damage.total_loss_candidate"))
    tl_paths = ("policy.insured_value", "loss.repair_estimate", "loss.recovery_estimate", "loss.residual_value")
    evidence = fact_evidence("total_loss.claimed", "damage.total_loss_candidate", *tl_paths) + document_evidence("policy")
    if not tl_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No ATL/CTL review signal is present."))
    else:
        missing = [label for path, label in (
            ("policy.insured_value", "insured value"),
            ("loss.repair_estimate", "repair estimate"),
            ("loss.recovery_estimate", "recovery estimate"),
        ) if fact(path) is None]
        if not doc_by_type.get("policy"):
            missing.append("applicable policy wording")
        if missing:
            evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, missing, "Total-loss review is indicated, but material valuation/recovery/policy prerequisites are missing."))
        else:
            evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "Core valuation/recovery facts and policy document are available; ATL/CTL analysis may proceed as a human technical/legal review."))

    rule = RULE_BY_ID["CP-COST-001"]
    cp_docs = doc_by_type.get("charterparty", [])
    allocation = fact("contract.cost_allocation_clause")
    evidence = fact_evidence("contract.cost_allocation_clause", "contract.cost_allocation_question") + document_evidence("charterparty")
    cp_signal = bool(cp_docs) or _truthy(fact("contract.charterparty_present"))
    if not cp_signal:
        evaluations.append(_evaluation(rule, MarineRuleStatus.NOT_APPLICABLE, evidence, (), "No reviewed charterparty/contract signal is present."))
    elif allocation is None:
        evaluations.append(_evaluation(rule, MarineRuleStatus.INSUFFICIENT_EVIDENCE, evidence, ("reviewed relevant contractual cost-allocation clause",), "A charterparty/contract is present, but no approved relevant allocation clause has been captured."))
    else:
        evaluations.append(_evaluation(rule, MarineRuleStatus.TRIGGERED, evidence, (), "A charterparty/contract and reviewed cost-allocation term are present; any allocation or recovery position remains for human contract analysis."))

    return tuple(evaluations)

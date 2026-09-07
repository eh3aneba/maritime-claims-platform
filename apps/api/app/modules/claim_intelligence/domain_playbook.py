from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.modules.claim_intelligence.domain_catalog import INCIDENT_DOMAINS, MACHINERY_COMPONENTS
from app.modules.claim_intelligence.domain_service import get_current_domain_classification
from app.modules.claims.models import Claim

DOMAIN_PLAYBOOK_REGISTRY_VERSION = "16.2-A.1"

DOMAIN_PLAYBOOKS: tuple[dict[str, object], ...] = (
    {
        "incident_code": "machinery_failure",
        "title": "Machinery Failure Investigation Preview",
        "objective": "Organize a bounded technical and adjusting investigation of the reported machinery casualty without deciding causation, coverage or recoverability.",
        "investigation_tracks": [
            "Reconstruct the casualty chronology, operating condition and immediate response.",
            "Review component condition, maintenance history, running hours, recent overhaul/work and maker guidance.",
            "Map damage, repair options, class involvement and potential third-party workmanship or part-recovery avenues.",
        ],
        "evidence_prompts": [
            "Engine log and relevant alarm/event records around the casualty.",
            "Noon reports and machinery performance records for the relevant pre-casualty period.",
            "PMS history, running-hours records, overhaul/inspection reports and maker recommendations.",
            "Clearance/measurement records, damaged-part photographs and preserved failed components where available.",
            "Class/survey findings, repair specification, workshop findings and repair/replacement quotations.",
        ],
        "review_topics": [
            "Technical failure mechanism and competing causation hypotheses.",
            "Maintenance interval, deferred work, recent overhaul/workmanship and part provenance.",
            "Temporary versus permanent repair scope, class conditions and repair reasonableness.",
            "Repair-related movement, fuel/stores and temporary service cost classification where evidenced.",
        ],
        "contextual_rule_ids": [
            "TECH-001",
            "TECH-002",
            "TECH-003",
            "TECH-006",
            "HM-REPAIR-001",
            "AAA-D1",
            "AAA-D2",
            "AAA-D6",
            "AAA-D9",
        ],
    },
    {
        "incident_code": "collision",
        "title": "Collision Investigation Preview",
        "objective": "Organize navigation, damage and recovery evidence for a collision review without determining fault, liability or apportionment.",
        "investigation_tracks": [
            "Reconstruct navigation, encounter geometry, communications and collision chronology.",
            "Map vessel damage, seaworthiness consequences, emergency measures and repair needs.",
            "Preserve third-party claim, security, contractual and recovery evidence for later human/legal review.",
        ],
        "evidence_prompts": [
            "VDR/S-VDR, AIS, ECDIS/chart data and bridge/deck log extracts for the relevant period.",
            "Passage plan, standing orders, watch records and material bridge communications.",
            "Master/officer statements, protest/collision statements and available third-party particulars.",
            "Damage photographs, survey reports, class/flag attendance and repair estimates.",
            "Relevant charterparty, policy, security and third-party correspondence where applicable.",
        ],
        "review_topics": [
            "Navigation chronology and evidence preservation; no fault conclusion is implied.",
            "Physical damage causation and separation of collision damage from pre-existing condition.",
            "Emergency towage/salvage, mitigation, repair location and operational consequences.",
            "Third-party security, recovery and contractual allocation questions for separate review.",
        ],
        "contextual_rule_ids": ["MARINE-EMERGENCY-001", "AAA-D1", "MIA-S78", "CP-COST-001"],
    },
    {
        "incident_code": "grounding",
        "title": "Grounding Investigation Preview",
        "objective": "Organize navigational, hull-condition and refloating/repair evidence for a grounding review without determining negligence, causation or coverage.",
        "investigation_tracks": [
            "Reconstruct navigation, position, charted conditions, draft/tide and grounding chronology.",
            "Assess hull/propulsion/rudder damage, ingress risk and class/flag restrictions.",
            "Review refloating, towage/salvage, lightering and movement-to-repair measures.",
        ],
        "evidence_prompts": [
            "VDR/S-VDR, AIS/ECDIS, charts, passage plan, bridge/deck logs and position records.",
            "Draft, tide/weather/current data and sounding/under-keel-clearance information where relevant.",
            "Damage surveys, underwater inspection, class/flag reports and repair specifications.",
            "Refloating/towage/salvage contracts, statements of fact, invoices and operational logs.",
            "Cargo/lightering records and pollution-prevention measures where applicable.",
        ],
        "review_topics": [
            "Grounding chronology and alternative navigational/technical explanations.",
            "Damage extent, seaworthiness restrictions and permanent repair scope.",
            "Emergency service classification, mitigation and movement-to-repair evidence.",
            "Potential pollution/cargo/GA interfaces requiring separately governed analysis.",
        ],
        "contextual_rule_ids": ["MARINE-EMERGENCY-001", "AAA-D1", "MIA-S78", "GA-YAR-001"],
    },
    {
        "incident_code": "fire",
        "title": "Fire Investigation Preview",
        "objective": "Organize origin, response, damage and mitigation evidence for a fire casualty without determining cause, policy response or liability.",
        "investigation_tracks": [
            "Reconstruct first indication, alarm, location, spread and firefighting chronology.",
            "Preserve origin/cause evidence and map heat, smoke, water and firefighting damage.",
            "Review emergency services, mitigation, class/flag requirements and repair consequences.",
        ],
        "evidence_prompts": [
            "Alarm/event logs, engine/deck logs, CCTV/VDR material and crew statements.",
            "Fire plan, firefighting system records, maintenance/testing history and inventory of extinguishing media used.",
            "Origin-and-cause survey/expert reports, photographs and preserved components/materials.",
            "Class/flag/authority attendance, damage surveys and repair specifications/quotations.",
            "Emergency-service, mitigation and pollution-response records where applicable.",
        ],
        "review_topics": [
            "Competing origin/cause hypotheses and evidence preservation.",
            "Firefighting response and separation of fire damage from consequential mitigation damage.",
            "Maintenance/testing of relevant safety systems without inferring breach or causation.",
            "Emergency expenditure, repair scope and possible third-party recovery questions.",
        ],
        "contextual_rule_ids": ["MIA-S78", "MARINE-EMERGENCY-001", "HM-REPAIR-001"],
    },
    {
        "incident_code": "cargo_damage",
        "title": "Cargo Damage Investigation Preview",
        "objective": "Organize carriage, condition and custody evidence for cargo damage without determining carrier liability, package limitation or policy response.",
        "investigation_tracks": [
            "Establish cargo condition, custody chain and timing/location of alleged damage.",
            "Review stowage, handling, ventilation/temperature, water ingress or contamination evidence as applicable.",
            "Preserve contractual, survey, mitigation and recovery material for later human/legal review.",
        ],
        "evidence_prompts": [
            "Bills of lading, cargo manifest, mate's receipts and relevant charterparty/booking terms.",
            "Pre-loading/loading/discharge surveys, tally/condition reports and photographs.",
            "Cargo hold/tank condition, cleaning, ventilation/temperature and weather/sea records as relevant.",
            "Notice of loss/damage, protest correspondence, joint survey invitations and claimant documents.",
            "Salvage sale, mitigation, disposal and valuation records where applicable.",
        ],
        "review_topics": [
            "Condition and custody chronology; no liability conclusion is implied.",
            "Physical mechanism of damage and evidential gaps.",
            "Contractual carriage terms and recovery rights for separately governed legal review.",
            "Mitigation, valuation and quantum support without automatic reserve or settlement action.",
        ],
        "contextual_rule_ids": ["CP-COST-001", "MIA-S78"],
    },
    {
        "incident_code": "pollution",
        "title": "Pollution Investigation Preview",
        "objective": "Organize source, quantity, response and cost evidence for a pollution event without determining statutory liability, coverage or recoverability.",
        "investigation_tracks": [
            "Identify the alleged source, pollutant, release chronology and estimated quantity/range.",
            "Track containment, cleanup, contractor and authority response measures.",
            "Preserve statutory, security, contractual and cost evidence for later specialist review.",
        ],
        "evidence_prompts": [
            "Deck/engine/cargo logs, tank/bunker records, transfer plans and relevant valve/pipeline records.",
            "Photographs/video, samples, survey reports and spill trajectory/quantity estimates.",
            "SOPEP/SMPEP records, notifications and communications with coastguard/port/environmental authorities.",
            "Cleanup/response contracts, daily reports, invoices, waste/disposal records and contractor timesheets.",
            "Security demands, fines/claims correspondence and relevant policy/charter documents where applicable.",
        ],
        "review_topics": [
            "Source and release mechanism as an investigation question, not a liability finding.",
            "Reasonableness and chronology of containment/cleanup measures.",
            "Authority/third-party claim evidence and jurisdiction-specific questions for separate legal review.",
            "Mitigation, emergency-service and contractual cost-allocation interfaces.",
        ],
        "contextual_rule_ids": ["MIA-S78", "MARINE-EMERGENCY-001", "CP-COST-001"],
    },
    {
        "incident_code": "salvage",
        "title": "Salvage Investigation Preview",
        "objective": "Organize danger, services, contractual/award and security evidence for salvage review without determining entitlement, award amount or policy recovery.",
        "investigation_tracks": [
            "Reconstruct the peril/danger and services rendered to ship, cargo and other property.",
            "Identify LOF/SCOPIC, commercial towage or other service terms and operational chronology.",
            "Track security, award/settlement, GA/Sue & Labour and allocation interfaces for later expert review.",
        ],
        "evidence_prompts": [
            "LOF, SCOPIC notice, towage/emergency-service contract or other governing service agreement.",
            "Casualty chronology, danger evidence, weather/sea conditions and services rendered.",
            "Salvor reports, tug logs, statements of fact, invoices and security correspondence.",
            "Cargo/value/property information and relevant policy wording where required for later allocation review.",
            "GA declaration/security and Sue & Labour material where those interfaces are raised.",
        ],
        "review_topics": [
            "Salvage versus contractual towage/emergency service classification.",
            "Danger, success, services and property/value evidence without determining an award.",
            "SCOPIC/LOF/security administration and preservation of recovery material.",
            "Overlap with GA, Sue & Labour and ordinary operational expenditure.",
        ],
        "contextual_rule_ids": ["MARINE-EMERGENCY-001", "MIA-S78", "GA-YAR-001", "CP-COST-001"],
    },
    {
        "incident_code": "general_average",
        "title": "General Average Investigation Preview",
        "objective": "Organize common-adventure, extraordinary sacrifice/expenditure and security evidence for General Average review without determining allowance or contribution liability.",
        "investigation_tracks": [
            "Confirm the casualty/common-adventure chronology and the extraordinary measure or sacrifice relied upon.",
            "Identify the incorporated York-Antwerp Rules edition and relevant contractual GA wording.",
            "Track expenditure, securities, contributory interests and overlap with salvage/Sue & Labour for adjustment review.",
        ],
        "evidence_prompts": [
            "GA declaration, casualty statement of facts and owner's/master's supporting reports.",
            "Bills of lading/charterparty and clauses incorporating the applicable York-Antwerp Rules edition.",
            "GA bond/guarantee/security records and cargo/freight/bunker interest details.",
            "Towage, salvage, STS/lightering, deviation, port and other extraordinary expenditure invoices/contracts/logs.",
            "Policy wording, absorption-clause material and adjuster correspondence where applicable.",
        ],
        "review_topics": [
            "Common danger/common safety and extraordinary nature of the measure as issues for adjustment review.",
            "Applicable YAR edition and contractual incorporation.",
            "Categorization of towage, salvage, deviation, STS/lightering, port, wages/fuel and related expenditure.",
            "Securities, contributory interests and overlap with H&M/Sue & Labour/absorption arrangements.",
        ],
        "contextual_rule_ids": ["GA-YAR-001", "MARINE-EMERGENCY-001", "MIA-S78", "CP-COST-001"],
    },
)

_INCIDENT_BY_CODE = {str(item["code"]): item for item in INCIDENT_DOMAINS}
_COMPONENT_BY_CODE = {str(item["code"]): item for item in MACHINERY_COMPONENTS}
_PLAYBOOK_BY_INCIDENT = {str(item["incident_code"]): item for item in DOMAIN_PLAYBOOKS}

if len(_PLAYBOOK_BY_INCIDENT) != len(DOMAIN_PLAYBOOKS):
    raise RuntimeError("Domain playbook registry contains duplicate incident codes")
if set(_PLAYBOOK_BY_INCIDENT) != set(_INCIDENT_BY_CODE):
    raise RuntimeError("Domain playbook registry must define exactly one playbook for every governed incident code")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def domain_playbook_registry_hash() -> str:
    payload = {
        "registry_version": DOMAIN_PLAYBOOK_REGISTRY_VERSION,
        "playbooks": DOMAIN_PLAYBOOKS,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def get_domain_playbook(incident_code: str) -> dict[str, object]:
    playbook = _PLAYBOOK_BY_INCIDENT.get(incident_code)
    if playbook is None:
        raise ValueError("No governed investigation playbook exists for the current claim incident domain")
    return json.loads(_canonical_json(playbook))


def domain_playbook_preview(db: Session, *, claim: Claim) -> dict[str, object]:
    current = get_current_domain_classification(db, claim=claim)
    base: dict[str, object] = {
        "registry_version": DOMAIN_PLAYBOOK_REGISTRY_VERSION,
        "registry_hash": domain_playbook_registry_hash(),
        "classification_required": current is None,
        "non_authoritative": True,
        "read_only_preview": True,
        "automatic_rule_execution": False,
        "automatic_requirement_activation": False,
        "automatic_task_creation": False,
        "automatic_claim_decision": False,
        "authority_boundary": (
            "This playbook is a read-only investigation preview derived from the latest human-confirmed claim-domain "
            "classification. It does not execute rules, activate evidence requirements, create tasks or determine "
            "coverage, causation, fault, liability, recoverability, reserve, settlement, payment or closure."
        ),
        "source_ref": None,
        "classification_context": None,
        "playbook": None,
    }
    if current is None:
        return base

    incident = _INCIDENT_BY_CODE.get(current.incident_code)
    if incident is None:
        raise ValueError("Current claim-domain classification is outside the governed incident catalog")
    component = _COMPONENT_BY_CODE.get(current.component_code) if current.component_code else None

    base.update(
        {
            "classification_required": False,
            "source_ref": {
                "kind": "claim_domain_classification",
                "id": str(current.id),
                "catalog_version": current.catalog_version,
                "classification_number": current.classification_number,
                "classification_hash": current.classification_hash,
            },
            "classification_context": {
                "incident_code": current.incident_code,
                "incident_title": str(incident["title"]),
                "component_code": current.component_code,
                "component_title": str(component["title"]) if component else None,
                "failure_mode": current.failure_mode,
            },
            "playbook": get_domain_playbook(current.incident_code),
        }
    )
    return base

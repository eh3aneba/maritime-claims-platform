from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.rules.marine_registry import MARINE_RULES, MarineRuleStatus, evaluate_marine_rules, registry_hash
from app.modules.rules.models import RuleEvaluationRun
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim
from tests.test_rules_engine import _add_fact, _set_status
from app.modules.claims.models import ClaimStatus


def setup_function() -> None:
    reset_database()


def _claim():
    return SimpleNamespace(id=uuid4(), incident_date=date(2026, 7, 10))


def _fact(path: str, value):
    return SimpleNamespace(
        id=uuid4(),
        field_path=path,
        value=value,
        source_document_id=uuid4(),
        source_extraction_id=uuid4(),
        source_segment_id=None,
        version=1,
    )


def _cost(description: str, category: str | None = None):
    return SimpleNamespace(
        id=uuid4(),
        document_id=uuid4(),
        description=description,
        category=category,
        amount=1000,
        currency="USD",
        review_status=SimpleNamespace(value="under_review"),
    )


def _document(document_type: str):
    return SimpleNamespace(id=uuid4(), document_type=document_type, version_number=1)


def _by_id(rows):
    return {row.rule_id: row for row in rows}


def test_registry_is_versioned_unique_and_content_addressed() -> None:
    ids = [rule.rule_id for rule in MARINE_RULES]
    assert len(ids) == len(set(ids))
    assert len(MARINE_RULES) >= 15
    assert len(registry_hash()) == 64
    assert all(len(rule.definition_hash) == 64 for rule in MARINE_RULES)
    assert registry_hash() == registry_hash()


def test_overdue_running_hours_is_triggered_without_causation_conclusion() -> None:
    rows = evaluate_marine_rules(
        claim=_claim(),
        fact_rows=[
            _fact("maintenance.running_hours_since_overhaul", 14800),
            _fact("maintenance.recommended_overhaul_interval", 12000),
        ],
        documents=[],
        costs=[],
    )
    rule = _by_id(rows)["TECH-001"]
    assert rule.status == MarineRuleStatus.TRIGGERED
    assert "causation finding" in rule.candidate_implication.lower()
    assert "caused" not in rule.rationale.lower()


def test_missing_overhaul_interval_is_insufficient_evidence() -> None:
    rows = evaluate_marine_rules(
        claim=_claim(),
        fact_rows=[_fact("maintenance.running_hours_since_overhaul", 14800)],
        documents=[],
        costs=[],
    )
    rule = _by_id(rows)["TECH-001"]
    assert rule.status == MarineRuleStatus.INSUFFICIENT_EVIDENCE
    assert "reviewed recommended overhaul interval" in rule.missing_prerequisites


def test_d1_requires_repair_purpose_not_just_towage_keyword() -> None:
    candidate = _cost("Emergency tug and towage invoice", "towage")
    insufficient = _by_id(evaluate_marine_rules(claim=_claim(), fact_rows=[], documents=[], costs=[candidate]))["AAA-D1"]
    assert insufficient.status == MarineRuleStatus.INSUFFICIENT_EVIDENCE
    assert any("repair" in item.lower() for item in insufficient.missing_prerequisites)

    triggered = _by_id(evaluate_marine_rules(
        claim=_claim(),
        fact_rows=[
            _fact("operational_impact.towage", True),
            _fact("towage.purpose", "Tow vessel to repair yard following machinery casualty"),
            _fact("repair.destination", "Repair yard"),
        ],
        documents=[],
        costs=[candidate],
    ))["AAA-D1"]
    assert triggered.status == MarineRuleStatus.TRIGGERED
    assert "does not decide recoverability" in triggered.candidate_implication.lower()


def test_d2_does_not_treat_all_bunkers_as_repair_consumption() -> None:
    bunker = _cost("Bunkers consumed during STS standby", "bunkers")
    insufficient = _by_id(evaluate_marine_rules(claim=_claim(), fact_rows=[], documents=[], costs=[bunker]))["AAA-D2"]
    assert insufficient.status == MarineRuleStatus.INSUFFICIENT_EVIDENCE

    triggered = _by_id(evaluate_marine_rules(
        claim=_claim(),
        fact_rows=[
            _fact("repair.fuel_consumed", True),
            _fact("repair.fuel_consumption_purpose", "Fuel consumed while machinery was operated for repair activity"),
        ],
        documents=[],
        costs=[bunker],
    ))["AAA-D2"]
    assert triggered.status == MarineRuleStatus.TRIGGERED
    assert "human adjusting review" in triggered.rationale.lower()


def test_d6_requires_evidence_that_machinery_assisted_repairs() -> None:
    machinery = _cost("Generator and crane operating cost", "repair_support")
    insufficient = _by_id(evaluate_marine_rules(claim=_claim(), fact_rows=[], documents=[], costs=[machinery]))["AAA-D6"]
    assert insufficient.status == MarineRuleStatus.INSUFFICIENT_EVIDENCE

    triggered = _by_id(evaluate_marine_rules(
        claim=_claim(),
        fact_rows=[
            _fact("repair.machinery_assisted", True),
            _fact("repair.machinery_assistance_purpose", "Crane and generator used specifically to assist repair work"),
        ],
        documents=[],
        costs=[machinery],
    ))["AAA-D6"]
    assert triggered.status == MarineRuleStatus.TRIGGERED


def test_temporary_generator_and_emergency_classification_are_fail_safe() -> None:
    generator = _cost("Temporary generator hire", "temporary_generator")
    d9 = _by_id(evaluate_marine_rules(
        claim=_claim(),
        fact_rows=[
            _fact("repair.temporary_generator", True),
            _fact("repair.temporary_generator_purpose", "Provide power required for repair works"),
        ],
        documents=[],
        costs=[generator],
    ))["AAA-D9"]
    assert d9.status == MarineRuleStatus.TRIGGERED

    tow = _cost("Emergency tug services", "towage")
    emergency = _by_id(evaluate_marine_rules(claim=_claim(), fact_rows=[], documents=[], costs=[tow]))["MARINE-EMERGENCY-001"]
    assert emergency.status == MarineRuleStatus.INSUFFICIENT_EVIDENCE
    assert "service contract/award" in emergency.missing_prerequisites[0]


def test_same_controlled_inputs_produce_same_evaluation_hash() -> None:
    facts = [
        _fact("maintenance.running_hours_since_overhaul", 14800),
        _fact("maintenance.recommended_overhaul_interval", 12000),
    ]
    claim = _claim()
    first = _by_id(evaluate_marine_rules(claim=claim, fact_rows=facts, documents=[], costs=[]))["TECH-001"]
    second = _by_id(evaluate_marine_rules(claim=claim, fact_rows=facts, documents=[], costs=[]))["TECH-001"]
    assert first.evaluation_hash == second.evaluation_hash


def test_rules_api_attaches_marine_evaluations_to_existing_rule_run_and_audits() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "maintenance.running_hours_since_overhaul", 14800)
    _add_fact(claim_id, "maintenance.recommended_overhaul_interval", 12000)

    response = client.post(f"/api/v1/claims/{claim_id}/rules/evaluate")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["marine_run_id"] == payload["run_id"]
    summary = payload["summary"]
    assert len(summary["marine_registry_hash"]) == 64
    assert len(summary["marine_rule_evaluations"]) == len(MARINE_RULES)
    tech = next(row for row in summary["marine_rule_evaluations"] if row["rule_id"] == "TECH-001")
    assert tech["status"] == "triggered"
    assert len(tech["definition_hash"]) == 64
    assert len(tech["evaluation_hash"]) == 64
    assert summary["human_authority_boundary"]

    with TestingSessionLocal() as db:
        runs = list(db.scalars(select(RuleEvaluationRun).where(RuleEvaluationRun.claim_id == UUID(claim_id))))
        assert len(runs) == 1
        assert runs[0].summary["marine_registry_hash"] == summary["marine_registry_hash"]
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "EVALUATE_MARINE_RULES", AuditLog.entity_id == runs[0].id))
        assert audit is not None


def test_rules_get_returns_latest_marine_evaluation_without_rerun() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    first = client.post(f"/api/v1/claims/{claim_id}/rules/evaluate")
    assert first.status_code == 200
    first_summary = first.json()["summary"]

    fetched = client.get(f"/api/v1/claims/{claim_id}/rules")
    assert fetched.status_code == 200
    fetched_summary = fetched.json()
    assert fetched_summary["marine_rule_run_id"] == first_summary["marine_rule_run_id"]
    assert fetched_summary["marine_registry_hash"] == first_summary["marine_registry_hash"]

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.modules.rules.marine_engine import MARINE_REGISTRY_VERSION, MARINE_RULES, REGISTRY_MANIFEST, evaluate_marine_rules, registry_hash
from app.modules.rules.marine_registry import MarineRuleStatus


def _claim(*, description: str = "Main engine turbocharger machinery casualty", status: str = "financial_review"):
    return SimpleNamespace(
        id=uuid4(),
        incident_date=date(2026, 7, 10),
        notification_date=date(2026, 7, 11),
        incident_description=description,
        status=SimpleNamespace(value=status),
    )


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
        amount=25000,
        currency="USD",
        review_status=SimpleNamespace(value="under_review"),
    )


def _document(document_type: str):
    return SimpleNamespace(id=uuid4(), document_type=document_type, version_number=1)


def _term(category: str, value: str, document_type: str = "policy"):
    return SimpleNamespace(
        extraction_id=uuid4(),
        category=category,
        value=value,
        source=SimpleNamespace(
            document_id=uuid4(),
            document_version=1,
            document_type=document_type,
            locator="page 1",
        ),
    )


def _policy(*terms):
    return SimpleNamespace(terms=list(terms), source_document_version_ids=[])


def _by_id(rows):
    return {row.rule_id: row for row in rows}


def test_composed_registry_is_new_immutable_version_over_base() -> None:
    ids = [rule.rule_id for rule in MARINE_RULES]
    assert MARINE_REGISTRY_VERSION == "12B.2.0"
    assert REGISTRY_MANIFEST["supersedes"] == "12B.1.0"
    assert len(ids) == len(set(ids))
    assert {"AAA-A4", "AAA-A5", "POLICY-WORDING-001", "GA-ABSORB-001"}.issubset(ids)
    assert len(registry_hash()) == 64
    assert registry_hash() == registry_hash()


def test_a4_requires_cost_reasonableness_evidence_and_accepts_quotation() -> None:
    repair_cost = _cost("Turbocharger repair labour and parts", "repair")
    without_quote = _by_id(evaluate_marine_rules(
        claim=_claim(), fact_rows=[], documents=[], costs=[repair_cost], policy=_policy()
    ))["AAA-A4"]
    assert without_quote.status == MarineRuleStatus.INSUFFICIENT_EVIDENCE
    assert any("quotation" in item.lower() for item in without_quote.missing_prerequisites)

    with_quote = _by_id(evaluate_marine_rules(
        claim=_claim(), fact_rows=[], documents=[_document("quotation")], costs=[repair_cost], policy=_policy()
    ))["AAA-A4"]
    assert with_quote.status == MarineRuleStatus.TRIGGERED
    assert "reasonableness" in with_quote.rationale.lower()


def test_a5_requires_residual_value_review_for_major_machinery_replacement() -> None:
    replacement = _cost("Replacement turbocharger new unit", "replacement")
    missing = _by_id(evaluate_marine_rules(
        claim=_claim(),
        fact_rows=[_fact("repair.replacement", True)],
        documents=[], costs=[replacement], policy=_policy(),
    ))["AAA-A5"]
    assert missing.status == MarineRuleStatus.INSUFFICIENT_EVIDENCE
    assert any("residual" in item.lower() for item in missing.missing_prerequisites)

    reviewed = _by_id(evaluate_marine_rules(
        claim=_claim(),
        fact_rows=[_fact("repair.replacement", True), _fact("repair.residual_value", 3500)],
        documents=[], costs=[replacement], policy=_policy(),
    ))["AAA-A5"]
    assert reviewed.status == MarineRuleStatus.TRIGGERED


def test_policy_rules_fail_safe_without_approved_wording() -> None:
    rows = _by_id(evaluate_marine_rules(
        claim=_claim(), fact_rows=[], documents=[], costs=[], policy=_policy()
    ))
    assert rows["POLICY-WORDING-001"].status == MarineRuleStatus.INSUFFICIENT_EVIDENCE
    assert rows["POLICY-DEDUCTIBLE-001"].status == MarineRuleStatus.INSUFFICIENT_EVIDENCE
    assert rows["POLICY-NOTICE-001"].status == MarineRuleStatus.INSUFFICIENT_EVIDENCE
    assert rows["POLICY-MACH-001"].status == MarineRuleStatus.INSUFFICIENT_EVIDENCE


def test_only_reviewed_policy_terms_drive_deductible_notice_and_machinery_prompts() -> None:
    policy = _policy(
        _term("deductible", "USD 100,000 machinery damage deductible"),
        _term("notice", "Prompt notice of casualty is required"),
        _term("clause_extension", "Additional Perils wording including due diligence"),
    )
    rows = _by_id(evaluate_marine_rules(
        claim=_claim(), fact_rows=[], documents=[], costs=[], policy=policy
    ))
    assert rows["POLICY-WORDING-001"].status == MarineRuleStatus.NOT_TRIGGERED
    assert rows["POLICY-DEDUCTIBLE-001"].status == MarineRuleStatus.TRIGGERED
    assert rows["POLICY-NOTICE-001"].status == MarineRuleStatus.TRIGGERED
    assert rows["POLICY-MACH-001"].status == MarineRuleStatus.TRIGGERED
    assert all(item["kind"] == "policy_term" for item in rows["POLICY-DEDUCTIBLE-001"].evidence_used)


def test_ga_absorption_requires_actual_reviewed_absorption_wording() -> None:
    ga_fact = _fact("ga.declared", True)
    missing_policy = _by_id(evaluate_marine_rules(
        claim=_claim(description="General Average declared after machinery casualty"),
        fact_rows=[ga_fact], documents=[], costs=[], policy=_policy(),
    ))["GA-ABSORB-001"]
    assert missing_policy.status == MarineRuleStatus.INSUFFICIENT_EVIDENCE

    ordinary_ga = _by_id(evaluate_marine_rules(
        claim=_claim(description="General Average declared after machinery casualty"),
        fact_rows=[ga_fact], documents=[], costs=[],
        policy=_policy(_term("general_average", "General Average shall be adjusted under the incorporated rules")),
    ))["GA-ABSORB-001"]
    assert ordinary_ga.status == MarineRuleStatus.NOT_APPLICABLE

    absorption = _by_id(evaluate_marine_rules(
        claim=_claim(description="General Average declared after machinery casualty"),
        fact_rows=[ga_fact], documents=[], costs=[],
        policy=_policy(_term("general_average", "General Average absorption up to the stated limit subject to policy conditions")),
    ))["GA-ABSORB-001"]
    assert absorption.status == MarineRuleStatus.TRIGGERED
    assert "does not determine" in absorption.candidate_implication.lower()


def test_charterparty_terms_are_not_inferred_from_document_presence() -> None:
    charter = _document("charter_party")
    missing = _by_id(evaluate_marine_rules(
        claim=_claim(description="Vessel under time charter"),
        fact_rows=[], documents=[charter], costs=[], policy=_policy(),
    ))["CP-WORDING-001"]
    assert missing.status == MarineRuleStatus.INSUFFICIENT_EVIDENCE

    reviewed = _by_id(evaluate_marine_rules(
        claim=_claim(description="Vessel under time charter"),
        fact_rows=[], documents=[charter], costs=[],
        policy=_policy(_term("charterparty_incorporation", "Reviewed off-hire and repair allocation clause", "charter_party")),
    ))["CP-WORDING-001"]
    assert reviewed.status == MarineRuleStatus.TRIGGERED

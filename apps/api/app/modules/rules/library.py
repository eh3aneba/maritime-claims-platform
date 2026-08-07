from __future__ import annotations

from dataclasses import dataclass

from app.modules.claims.models import ClaimStatus
from app.modules.rules.models import IssueCategory, IssueSeverity, RequirementPriority

RULESET_NAME = "hm_machinery_rules"
RULESET_VERSION = "1.0"

STATUS_RANK: dict[ClaimStatus, int] = {
    ClaimStatus.NEW: 0,
    ClaimStatus.TRIAGE: 1,
    ClaimStatus.AWAITING_DOCUMENTS: 2,
    ClaimStatus.INVESTIGATION: 3,
    ClaimStatus.TECHNICAL_REVIEW: 4,
    ClaimStatus.FINANCIAL_REVIEW: 5,
    ClaimStatus.COVERAGE_REVIEW: 6,
    ClaimStatus.NEGOTIATION: 7,
    ClaimStatus.SETTLEMENT: 8,
    ClaimStatus.RECOVERY: 9,
    ClaimStatus.CLOSED: 0,
    ClaimStatus.ON_HOLD: 3,
    ClaimStatus.LITIGATION: 7,
    ClaimStatus.REJECTED: 0,
    ClaimStatus.WITHDRAWN: 0,
}


@dataclass(frozen=True)
class DocumentRule:
    rule_id: str
    document_type: str
    label: str
    priority: RequirementPriority
    required_from: ClaimStatus
    reason: str
    condition: str = "always"


DOCUMENT_RULES: tuple[DocumentRule, ...] = (
    DocumentRule("DOC-001", "chief_engineer_report", "Chief Engineer Report", RequirementPriority.CRITICAL, ClaimStatus.TRIAGE, "Establishes the reported machinery casualty narrative, first observations and immediate actions."),
    DocumentRule("DOC-002", "engine_log", "Engine Log", RequirementPriority.CRITICAL, ClaimStatus.TRIAGE, "Provides contemporaneous machinery timestamps and operating evidence for chronology and technical review."),
    DocumentRule("DOC-003", "workshop_report", "Workshop Report", RequirementPriority.CRITICAL, ClaimStatus.INVESTIGATION, "Required to establish inspected damage, repairability and workshop findings."),
    DocumentRule("DOC-004", "policy", "H&M Policy / Wording", RequirementPriority.CRITICAL, ClaimStatus.TRIAGE, "Required before coverage issues, deductibles and relevant policy wording can be assessed."),
    DocumentRule("DOC-005", "running_hours_record", "Running Hours Record", RequirementPriority.CRITICAL, ClaimStatus.INVESTIGATION, "Required to evaluate turbocharger service life and hours since the previous overhaul.", "turbocharger"),
    DocumentRule("DOC-006", "overhaul_report", "Last Overhaul Report", RequirementPriority.CRITICAL, ClaimStatus.INVESTIGATION, "Required to evaluate the scope, timing and findings of the previous turbocharger overhaul.", "turbocharger"),
    DocumentRule("DOC-007", "pms_record", "PMS History", RequirementPriority.CRITICAL, ClaimStatus.INVESTIGATION, "Required to evaluate planned maintenance status and any deferred or overdue work.", "turbocharger"),
    DocumentRule("DOC-008", "maker_recommendation", "Maker Recommended Overhaul Interval", RequirementPriority.IMPORTANT, ClaimStatus.INVESTIGATION, "Required to compare actual running hours with the maker's stated maintenance interval.", "turbocharger"),
    DocumentRule("DOC-009", "quotation", "Repair Quotation", RequirementPriority.IMPORTANT, ClaimStatus.FINANCIAL_REVIEW, "Required for scope and cost review before financial assessment."),
    DocumentRule("DOC-010", "final_invoice", "Final Repair Invoice", RequirementPriority.CRITICAL, ClaimStatus.SETTLEMENT, "Required before final financial adjustment and settlement readiness can be assessed."),
    DocumentRule("DOC-011", "class_report", "Class Attendance / Approval", RequirementPriority.IMPORTANT, ClaimStatus.INVESTIGATION, "Required because reviewed claim facts indicate Class attendance or approval.", "class_attended"),
    DocumentRule("DOC-012", "towage_contract", "Towage Contract", RequirementPriority.CRITICAL, ClaimStatus.INVESTIGATION, "Required because reviewed evidence indicates towage was required.", "towage"),
    DocumentRule("DOC-013", "towage_invoice", "Towage Invoice", RequirementPriority.IMPORTANT, ClaimStatus.FINANCIAL_REVIEW, "Required to review the claimed towage expenditure.", "towage"),
    DocumentRule("DOC-014", "towage_report", "Towage / Tug Report", RequirementPriority.IMPORTANT, ClaimStatus.INVESTIGATION, "Required to review the towage operation and necessity evidence.", "towage"),
    DocumentRule("DOC-015", "temporary_repair_specification", "Temporary Repair Specification", RequirementPriority.CRITICAL, ClaimStatus.TECHNICAL_REVIEW, "Required because reviewed facts indicate a temporary repair.", "temporary_repair"),
    DocumentRule("DOC-016", "permanent_repair_plan", "Permanent Repair Plan", RequirementPriority.IMPORTANT, ClaimStatus.TECHNICAL_REVIEW, "Required to establish the outstanding permanent repair following a temporary repair.", "temporary_repair"),
)


@dataclass(frozen=True)
class IssueRuleMetadata:
    rule_id: str
    category: IssueCategory
    title: str
    severity: IssueSeverity
    explanation: str


TECH_OVERDUE = IssueRuleMetadata(
    "TECH-001", IssueCategory.TECHNICAL, "Possible overdue maintenance", IssueSeverity.HIGH,
    "Running hours since overhaul exceed the reviewed recommended overhaul interval. This is an investigation flag, not a causation finding.",
)
TECH_RECENT_OVERHAUL = IssueRuleMetadata(
    "TECH-002", IssueCategory.TECHNICAL, "Failure occurred soon after overhaul", IssueSeverity.HIGH,
    "The casualty occurred within 90 days of the reviewed last overhaul date. Review workmanship, assembly, replaced components and post-overhaul testing.",
)
TECH_TEMP_REPAIR = IssueRuleMetadata(
    "TECH-006", IssueCategory.TECHNICAL, "Temporary repair remains subject to permanent repair review", IssueSeverity.HIGH,
    "Reviewed facts indicate a temporary repair. Confirm Class conditions, expiry and the permanent repair plan.",
)

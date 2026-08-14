from __future__ import annotations

from datetime import UTC, date, datetime
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.models import Claim
from app.modules.claims.service import get_claim
from app.modules.documents.models import Document
from app.modules.intelligence.models import AIReviewStatus, DocumentExtraction
from app.modules.policy_intelligence.extractor import (
    ALLOWED_POLICY_DOCUMENT_TYPES,
    CATEGORY_TITLES,
)
from app.modules.policy_intelligence.schemas import (
    PolicyIntelligenceResponse,
    PolicyIntelligenceSummary,
    PolicyIssueSpot,
    PolicyTermSource,
    ReviewedPolicyTerm,
)


DISCLAIMER = (
    "Issue spotting only. This workspace does not decide coverage, apply an "
    "exclusion or warranty, calculate indemnity, or determine liability, "
    "causation, fraud, recoverability, reserve or settlement."
)


def _category(field_path: str) -> str:
    return field_path.split(".", 1)[1].split("[", 1)[0]


def _approved_value(extraction: DocumentExtraction) -> Any:
    if extraction.approved_value is not None:
        return extraction.approved_value
    return extraction.normalized_value


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _deduplicate(
    rows: list[tuple[DocumentExtraction, Document]],
) -> list[tuple[DocumentExtraction, Document]]:
    rows.sort(
        key=lambda pair: (
            pair[0].reviewed_at or pair[0].created_at,
            pair[0].created_at,
        ),
        reverse=True,
    )
    seen: set[tuple[str, UUID, str]] = set()
    kept: list[tuple[DocumentExtraction, Document]] = []
    for extraction, document in rows:
        key = (
            _category(extraction.field_path),
            document.document_family_id,
            json.dumps(_approved_value(extraction), sort_keys=True, default=str),
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append((extraction, document))
    kept.sort(
        key=lambda pair: (
            _category(pair[0].field_path),
            not pair[1].is_current,
            pair[1].version_number,
            pair[0].created_at,
        )
    )
    return kept


def build_policy_intelligence(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
) -> PolicyIntelligenceResponse:
    claim = get_claim(
        db,
        claim_id=claim_id,
        organization_id=organization_id,
    )
    policy_documents = list(
        db.scalars(
            select(Document).where(
                Document.organization_id == organization_id,
                Document.claim_id == claim.id,
                Document.deleted_at.is_(None),
                Document.document_type.in_(ALLOWED_POLICY_DOCUMENT_TYPES),
            )
        )
    )
    rows = list(
        db.execute(
            select(DocumentExtraction, Document)
            .join(Document, Document.id == DocumentExtraction.document_id)
            .where(
                DocumentExtraction.organization_id == organization_id,
                DocumentExtraction.claim_id == claim.id,
                DocumentExtraction.field_path.like("policy.%"),
                DocumentExtraction.human_status.in_(
                    [AIReviewStatus.APPROVED, AIReviewStatus.EDITED]
                ),
                Document.organization_id == organization_id,
                Document.claim_id == claim.id,
                Document.deleted_at.is_(None),
            )
        ).all()
    )
    reviewed_rows = _deduplicate(rows)
    terms = [
        ReviewedPolicyTerm(
            extraction_id=extraction.id,
            category=_category(extraction.field_path),
            title=CATEGORY_TITLES.get(
                _category(extraction.field_path),
                _category(extraction.field_path).replace("_", " ").title(),
            ),
            value=_approved_value(extraction),
            human_status=extraction.human_status.value,
            confidence=str(extraction.confidence),
            reviewed_at=extraction.reviewed_at,
            source=PolicyTermSource(
                document_id=document.id,
                document_family_id=document.document_family_id,
                document_name=document.original_filename,
                document_type=document.document_type,
                document_version=document.version_number,
                document_is_current=document.is_current,
                source_locator_type=extraction.source_locator_type,
                source_locator_value=extraction.source_locator_value,
                source_quote=extraction.source_quote,
                source_verified=extraction.source_verified,
            ),
        )
        for extraction, document in reviewed_rows
    ]
    by_category: dict[str, list[ReviewedPolicyTerm]] = {}
    for term in terms:
        by_category.setdefault(term.category, []).append(term)

    issues: list[PolicyIssueSpot] = []

    def add_issue(
        code: str,
        severity: str,
        title: str,
        description: str,
        trigger: dict[str, Any],
        action: str,
        related: list[ReviewedPolicyTerm] | None = None,
    ) -> None:
        issues.append(
            PolicyIssueSpot(
                code=code,
                severity=severity,
                title=title,
                description=description,
                trigger=trigger,
                required_human_action=action,
                related_extraction_ids=[
                    term.extraction_id for term in (related or [])
                ],
            )
        )

    current_policy_documents = [item for item in policy_documents if item.is_current]
    historical_policy_documents = [item for item in policy_documents if not item.is_current]
    if not current_policy_documents:
        add_issue(
            "policy_document_missing",
            "critical",
            "Current policy/contract wording is not available",
            "No current active document is classified as a supported policy or contract source.",
            {"supported_document_types": sorted(ALLOWED_POLICY_DOCUMENT_TYPES)},
            "Obtain, securely upload and classify the complete current wording and endorsements before coverage review.",
        )

    core_categories = {
        "policy_period": "Policy period",
        "deductible": "Deductible / excess",
    }
    for category, label in core_categories.items():
        if category not in by_category:
            add_issue(
                f"missing_{category}",
                "high",
                f"{label} has not been human-reviewed",
                f"No approved or edited {label.lower()} term is available in the reviewed register.",
                {"missing_category": category},
                f"Review the relevant policy source and approve or edit the {label.lower()} candidate.",
            )
    if not ({"insured_value", "limit"} & set(by_category)):
        add_issue(
            "missing_insured_value_or_limit",
            "high",
            "Insured value or limit has not been human-reviewed",
            "The reviewed register contains neither an insured/agreed value nor a limit term.",
            {"missing_categories": ["insured_value", "limit"]},
            "Review the schedule and wording and confirm the applicable insured value and limits.",
        )

    for term in by_category.get("policy_period", []):
        if not isinstance(term.value, dict):
            continue
        start = _date(term.value.get("start_date"))
        end = _date(term.value.get("end_date"))
        if start and claim.incident_date < start or end and claim.incident_date > end:
            add_issue(
                "incident_date_outside_extracted_policy_period",
                "high",
                "Incident date may fall outside the extracted policy period",
                "The incident date does not fall within the dates extracted from this reviewed term. This is a review trigger, not a coverage conclusion.",
                {
                    "incident_date": claim.incident_date.isoformat(),
                    "start_date": start.isoformat() if start else None,
                    "end_date": end.isoformat() if end else None,
                },
                "Verify attachment, expiry, time zone, renewals, endorsements and any held-covered or continuity wording.",
                [term],
            )

    elapsed_days = (claim.notification_date - claim.incident_date).days
    for term in by_category.get("notice_requirement", []):
        if not isinstance(term.value, dict):
            continue
        deadline_days = term.value.get("deadline_days")
        if isinstance(deadline_days, int) and elapsed_days > deadline_days:
            add_issue(
                "possible_notice_timing_issue",
                "high",
                "Notification timing requires review",
                "Recorded notification occurred after the extracted day-based notice period. This does not determine breach, prejudice or coverage.",
                {
                    "elapsed_days": elapsed_days,
                    "extracted_deadline_days": deadline_days,
                    "incident_date": claim.incident_date.isoformat(),
                    "notification_date": claim.notification_date.isoformat(),
                },
                "Verify when notice was first given, to whom, the complete clause wording, waiver, prejudice and governing-law requirements.",
                [term],
            )

    if by_category.get("exclusion"):
        add_issue(
            "exclusions_require_applicability_review",
            "medium",
            "Reviewed exclusions require claim-specific analysis",
            "One or more exclusion clauses are present. The system has not matched or applied them to the casualty.",
            {"reviewed_exclusion_count": len(by_category["exclusion"])},
            "A qualified claims handler or lawyer must review the full wording, facts, causation and applicable law.",
            by_category["exclusion"],
        )
    if by_category.get("warranty"):
        add_issue(
            "warranties_require_compliance_review",
            "medium",
            "Reviewed warranties or conditions require compliance review",
            "One or more warranty/condition terms are present. No compliance or remedy conclusion has been made.",
            {"reviewed_warranty_count": len(by_category["warranty"])},
            "Verify the assured's compliance, material timing, remedy and governing-law effect using source evidence.",
            by_category["warranty"],
        )
    if by_category.get("time_limit"):
        add_issue(
            "time_limits_require_diarising",
            "high",
            "Reviewed time limits require human calculation and diarising",
            "A contractual or statutory time-limit candidate is present; the system has not calculated the operative deadline.",
            {"reviewed_time_limit_count": len(by_category["time_limit"])},
            "Confirm the trigger date, applicable wording/law, extensions and protective-action deadline, then diary it.",
            by_category["time_limit"],
        )
    if "governing_law" not in by_category:
        add_issue(
            "governing_law_not_reviewed",
            "info",
            "Governing law has not been established",
            "No reviewed governing-law term is present.",
            {"missing_category": "governing_law"},
            "Check the schedule, wording, endorsements and incorporated rules.",
        )
    if "dispute_resolution" not in by_category:
        add_issue(
            "dispute_resolution_not_reviewed",
            "info",
            "Dispute-resolution mechanism has not been established",
            "No reviewed jurisdiction or arbitration term is present.",
            {"missing_category": "dispute_resolution"},
            "Check jurisdiction, arbitration seat, rules and service provisions.",
        )

    superseded_terms = [term for term in terms if not term.source.document_is_current]
    if superseded_terms:
        add_issue(
            "reviewed_terms_from_superseded_sources",
            "high",
            "Reviewed terms still cite superseded policy/contract versions",
            "One or more approved terms originate from a historical source version. Approval never transfers to replacement wording.",
            {"superseded_term_count": len(superseded_terms)},
            "Review the current replacement wording and approve new candidates before relying on these terms.",
            superseded_terms,
        )

    issues.sort(
        key=lambda item: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}[item.severity],
            item.code,
        )
    )
    categories = set(by_category)
    return PolicyIntelligenceResponse(
        claim_id=claim.id,
        generated_at=datetime.now(UTC),
        terms=terms,
        issue_spots=issues,
        summary=PolicyIntelligenceSummary(
            reviewed_term_count=len(terms),
            current_policy_document_count=len(current_policy_documents),
            historical_policy_document_count=len(historical_policy_documents),
            issue_count=len(issues),
            high_priority_issue_count=sum(
                1 for item in issues if item.severity in {"critical", "high"}
            ),
            has_policy_period="policy_period" in categories,
            has_insured_value_or_limit=bool(
                {"insured_value", "limit"} & categories
            ),
            has_deductible="deductible" in categories,
        ),
        disclaimer=DISCLAIMER,
    )

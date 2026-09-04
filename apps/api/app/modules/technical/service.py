from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.facts import ClaimFact
from app.modules.documents.models import (
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.intelligence.models import AISemanticKind, AIReviewStatus, DocumentExtraction
from app.modules.rules.models import ClaimIssue, IssueCategory


REVIEWED = {AIReviewStatus.APPROVED, AIReviewStatus.EDITED}
USABLE_MALWARE_STATES = {
    DocumentMalwareScanStatus.CLEAN,
    DocumentMalwareScanStatus.LEGACY_UNSCANNED,
}
TECHNICAL_FACT_PATHS = {"repair.temporary", "workshop.repairable"}


def _is_technical_fact(fact: ClaimFact) -> bool:
    return fact.field_path.startswith("maintenance.") or fact.field_path in TECHNICAL_FACT_PATHS


def _reviewed_extractions(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
    prefix: str,
) -> list[tuple[DocumentExtraction, Document]]:
    rows = db.execute(
        select(DocumentExtraction, Document)
        .join(Document, Document.id == DocumentExtraction.document_id)
        .where(
            DocumentExtraction.claim_id == claim_id,
            DocumentExtraction.organization_id == organization_id,
            DocumentExtraction.human_status.in_(REVIEWED),
            DocumentExtraction.field_path.like(f"{prefix}%"),
            Document.organization_id == organization_id,
            Document.claim_id == claim_id,
            Document.is_current.is_(True),
            Document.deleted_at.is_(None),
            Document.processing_status == DocumentProcessingStatus.PROCESSED,
            Document.malware_scan_status.in_(USABLE_MALWARE_STATES),
        )
        .order_by(DocumentExtraction.field_path.asc(), DocumentExtraction.id.asc())
    ).all()
    return [(row[0], row[1]) for row in rows]


def _value(ex: DocumentExtraction) -> Any:
    return ex.approved_value if ex.human_status == AIReviewStatus.EDITED else (
        ex.normalized_value if ex.normalized_value is not None else ex.raw_value
    )


def _evidence(ex: DocumentExtraction, document: Document) -> dict[str, Any]:
    return {
        "extraction_id": ex.id,
        "field_path": ex.field_path,
        "value": _value(ex),
        "document_id": ex.document_id,
        "document_version": document.version_number,
        "document_is_current": document.is_current and document.deleted_at is None,
        "document_processing_status": document.processing_status.value,
        "document_malware_scan_status": document.malware_scan_status.value,
        "source_state": "current_usable",
        "source_quote": ex.source_quote,
        "source_locator_type": ex.source_locator_type,
        "source_locator_value": ex.source_locator_value,
        "source_verified": ex.source_verified,
    }


def _json_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _technical_state_fingerprint(
    *,
    facts: list[ClaimFact],
    workshop_rows: list[tuple[DocumentExtraction, Document]],
    issues: list[ClaimIssue],
) -> str:
    fact_state = [
        {
            "field_path": fact.field_path,
            "version": fact.version,
            "value": fact.value,
            "provenance_kind": fact.provenance_kind,
            "source_document_id": fact.source_document_id,
            "source_extraction_id": fact.source_extraction_id,
            "source_text_extraction_id": fact.source_text_extraction_id,
        }
        for fact in sorted((item for item in facts if _is_technical_fact(item)), key=lambda item: item.field_path)
    ]
    workshop_state = [
        {
            "extraction_id": ex.id,
            "field_path": ex.field_path,
            "human_status": ex.human_status.value,
            "semantic_kind": ex.semantic_kind.value,
            "value": _value(ex),
            "document_id": document.id,
            "document_version": document.version_number,
            "document_file_hash": document.file_hash,
            "document_processing_status": document.processing_status.value,
            "document_malware_scan_status": document.malware_scan_status.value,
        }
        for ex, document in sorted(workshop_rows, key=lambda row: (row[0].field_path, str(row[0].id)))
    ]
    issue_state = [
        {
            "issue_key": issue.issue_key,
            "rule_id": issue.rule_id,
            "rule_version": issue.rule_version,
            "severity": issue.severity.value,
            "status": issue.status.value,
            "evidence": issue.evidence,
            "explanation": issue.explanation,
            "description": issue.description,
        }
        for issue in sorted(issues, key=lambda item: item.issue_key)
    ]
    return _json_fingerprint(
        {
            "technical_facts": fact_state,
            "workshop_evidence": workshop_state,
            "technical_issues": issue_state,
        }
    )


def _follow_up_for_opinion(text: str) -> tuple[list[str], list[str]]:
    lowered = text.lower()
    missing: list[str] = []
    follow: list[str] = []
    if any(word in lowered for word in ("lubric", "oil starvation", "low oil")):
        missing += [
            "Lubricating-oil analysis / condition evidence",
            "Relevant lube-oil alarms, filters and pump records",
        ]
        follow += ["Review lube-oil analysis, filter inspection, pump condition and alarm history."]
    if "bearing" in lowered:
        missing += ["Bearing measurements / clearances", "Bearing condition photographs or inspection records"]
        follow += ["Obtain bearing measurements, clearances and workshop photographs."]
    if any(word in lowered for word in ("foreign object", "fod", "foreign material")):
        missing += ["Foreign-object inspection evidence", "Compressor/turbine blade photographs"]
        follow += ["Review physical evidence supporting foreign-object ingress and damage path."]
    if any(word in lowered for word in ("assembly", "workmanship", "incorrect fitting")):
        missing += ["Previous overhaul scope and assembly records", "Post-overhaul clearances / commissioning results"]
        follow += ["Review previous overhaul workmanship, assembly records and post-overhaul testing."]
    if not missing:
        missing.append("Independent technical evidence supporting or contradicting the source opinion")
        follow.append("Test the workshop opinion against logs, maintenance history, measurements and survey evidence.")
    return missing, follow


def build_technical_review(db: Session, *, claim_id: UUID, organization_id: UUID) -> dict[str, Any]:
    facts = list(
        db.scalars(
            select(ClaimFact).where(
                ClaimFact.claim_id == claim_id,
                ClaimFact.organization_id == organization_id,
            )
        )
    )
    fact_map = {fact.field_path: fact.value for fact in facts}
    technical_facts = [fact for fact in facts if _is_technical_fact(fact)]
    maintenance = {fact.field_path: fact.value for fact in technical_facts}

    workshop_findings = _reviewed_extractions(
        db,
        claim_id=claim_id,
        organization_id=organization_id,
        prefix="workshop.damage_findings[",
    )
    repair_options = _reviewed_extractions(
        db,
        claim_id=claim_id,
        organization_id=organization_id,
        prefix="workshop.repair_options[",
    )
    cause_opinions = [
        row
        for row in _reviewed_extractions(
            db,
            claim_id=claim_id,
            organization_id=organization_id,
            prefix="workshop.suspected_cause_opinions[",
        )
        if row[0].semantic_kind == AISemanticKind.OPINION
    ]
    issues = list(
        db.scalars(
            select(ClaimIssue)
            .where(
                ClaimIssue.claim_id == claim_id,
                ClaimIssue.organization_id == organization_id,
                ClaimIssue.category == IssueCategory.TECHNICAL,
                ClaimIssue.is_active.is_(True),
            )
            .order_by(ClaimIssue.severity.desc(), ClaimIssue.title.asc())
        )
    )

    matrix: list[dict[str, Any]] = []
    for issue in issues:
        unknown: list[str] = []
        against: list[Any] = []
        follow: list[str] = []
        if issue.rule_id == "TECH-001":
            if fact_map.get("maintenance.interval_extension_approved") is True:
                against.append(
                    {
                        "interval_extension_approved": True,
                        "details": fact_map.get("maintenance.interval_extension_details"),
                    }
                )
                follow.append(
                    "Verify the maker/authorized extension scope and effective interval before drawing any maintenance conclusion."
                )
            else:
                unknown.append("Maker-approved interval extension has not been established.")
                follow.append("Request any maker/authorized extension approval and the applicable revised interval.")
        elif issue.rule_id == "TECH-002":
            unknown += [
                "Previous overhaul scope",
                "Assembly/workmanship evidence",
                "Post-overhaul testing and clearances",
            ]
            follow.append(
                "Review the previous overhaul report, replaced/reused parts, assembly records and commissioning results."
            )
        elif issue.rule_id == "TECH-003":
            unknown += [
                "Technical justification for deferral",
                "Deferral approval / risk assessment",
                "Whether deferred task is technically related to damaged component",
            ]
            follow.append("Obtain the PMS deferral basis, approval and any risk assessment before assessing relevance.")
        elif issue.rule_id == "TECH-006":
            unknown += ["Class conditions / expiry", "Permanent repair scope and completion plan"]
            follow.append("Confirm Class approval conditions and permanent repair requirement.")
        matrix.append(
            {
                "key": issue.issue_key,
                "title": issue.title,
                "severity": issue.severity.value,
                "status": issue.status.value,
                "evidence_for": [issue.evidence] if issue.evidence else [],
                "evidence_against": against,
                "unknown_or_missing": unknown,
                "recommended_follow_up": follow,
                "explanation": issue.explanation or issue.description,
            }
        )

    for index, (opinion, document) in enumerate(cause_opinions):
        text = str(_value(opinion) or "")
        missing, follow = _follow_up_for_opinion(text)
        matrix.append(
            {
                "key": f"workshop_opinion_{index}",
                "title": f"Workshop cause opinion: {text[:100]}",
                "severity": "medium",
                "status": "under_review",
                "evidence_for": [_evidence(opinion, document)],
                "evidence_against": [],
                "unknown_or_missing": missing,
                "recommended_follow_up": follow,
                "explanation": (
                    "This is a human-reviewed source opinion, not a confirmed cause. "
                    "It must be tested against independent technical evidence."
                ),
            }
        )

    workshop_rows = workshop_findings + repair_options + cause_opinions
    return {
        "evidence_state_fingerprint": _technical_state_fingerprint(
            facts=facts,
            workshop_rows=workshop_rows,
            issues=issues,
        ),
        "canonical_fact_versions": {fact.field_path: fact.version for fact in technical_facts},
        "maintenance_facts": maintenance,
        "workshop_findings": [_evidence(ex, document) for ex, document in workshop_findings],
        "workshop_repair_options": [_evidence(ex, document) for ex, document in repair_options],
        "workshop_cause_opinions": [_evidence(ex, document) for ex, document in cause_opinions],
        "matrix": matrix,
        "generated_at": datetime.now(UTC),
    }

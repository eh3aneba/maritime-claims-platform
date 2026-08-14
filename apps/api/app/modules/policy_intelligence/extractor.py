from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.intelligence.models import (
    AIRun,
    AIRunStatus,
    AISemanticKind,
    AIReviewStatus,
    DocumentExtraction,
)
from app.modules.policy_intelligence.schemas import (
    PolicyExtractionCandidate,
    PolicyExtractionResponse,
)
from app.modules.processing.models import DocumentTextSegment
from app.modules.users.models import User


ALLOWED_POLICY_DOCUMENT_TYPES = {
    "policy",
    "policy_wording",
    "hm_policy",
    "h&m_policy",
    "insurance_contract",
    "charter_party",
    "contract",
    "endorsement",
}

CATEGORY_TITLES = {
    "policy_period": "Policy period",
    "insured_value": "Insured / agreed value",
    "limit": "Limit",
    "deductible": "Deductible / excess",
    "notice_requirement": "Notice requirement",
    "time_limit": "Time limit / time bar",
    "governing_law": "Governing law",
    "dispute_resolution": "Dispute resolution",
    "exclusion": "Exclusion",
    "warranty": "Warranty / condition",
    "classification_maintenance": "Classification / maintenance obligation",
    "general_average": "General Average",
    "collision": "Collision liability",
    "sue_and_labour": "Sue and Labour",
    "salvage_towage": "Salvage / towage",
    "pollution_wreck": "Pollution / wreck removal",
    "war_risk": "War-risk wording",
    "clause_extension": "Clause / extension",
}

_RULES: tuple[tuple[str, re.Pattern[str], Decimal], ...] = (
    ("policy_period", re.compile(r"\b(period of insurance|policy period|inception|expiry|effective from|from .{0,80} to)\b", re.I), Decimal("0.900")),
    ("insured_value", re.compile(r"\b(sum insured|insured value|agreed value|insured amount)\b", re.I), Decimal("0.930")),
    ("limit", re.compile(r"\b(limit of liability|limit of cover|aggregate limit|any one occurrence|any one accident)\b", re.I), Decimal("0.900")),
    ("deductible", re.compile(r"\b(deductible|excess|each and every loss)\b", re.I), Decimal("0.940")),
    ("notice_requirement", re.compile(r"\b(notice|notify|notification)\b.*\b(days?|hours?|immediately|promptly|forthwith|as soon as practicable)\b", re.I), Decimal("0.880")),
    ("time_limit", re.compile(r"\b(time bar|time limit|limitation period|suit must|proceedings must|within \d+ (?:months?|years?))\b", re.I), Decimal("0.880")),
    ("governing_law", re.compile(r"\b(governing law|governed by|applicable law)\b", re.I), Decimal("0.930")),
    ("dispute_resolution", re.compile(r"\b(arbitration|jurisdiction|dispute resolution|exclusive jurisdiction)\b", re.I), Decimal("0.920")),
    ("exclusion", re.compile(r"\b(exclusion|excluded|in no case shall|shall not be liable|not covered)\b", re.I), Decimal("0.870")),
    ("warranty", re.compile(r"\b(warranted|warranty|condition precedent|subject to the condition)\b", re.I), Decimal("0.880")),
    ("classification_maintenance", re.compile(r"\b(classification society|class maintained|class recommendations|planned maintenance|due diligence)\b", re.I), Decimal("0.870")),
    ("general_average", re.compile(r"\b(general average|york[- ]antwerp)\b", re.I), Decimal("0.920")),
    ("collision", re.compile(r"\b(collision liability|running down clause|three[- ]fourths collision|4/4ths collision)\b", re.I), Decimal("0.920")),
    ("sue_and_labour", re.compile(r"\b(sue and labour|sue & labour|duty of assured)\b", re.I), Decimal("0.920")),
    ("salvage_towage", re.compile(r"\b(salvage|salvage charges|towage|tow hire)\b", re.I), Decimal("0.850")),
    ("pollution_wreck", re.compile(r"\b(pollution|contamination|wreck removal|removal of wreck)\b", re.I), Decimal("0.850")),
    ("war_risk", re.compile(r"\b(war risks?|capture|seizure|arrest|restraint|detainment|terrorism|hostilities)\b", re.I), Decimal("0.850")),
    ("clause_extension", re.compile(r"\b(clause|extension|held covered|additional cover)\b", re.I), Decimal("0.780")),
)

_MONEY = re.compile(
    r"\b(?P<currency>USD|EUR|GBP|AED|IRR|CNY|JPY)\s*(?P<amount>[0-9][0-9,]*(?:\.\d+)?)\b",
    re.I,
)
_PERCENTAGE = re.compile(r"(?P<percentage>\d+(?:\.\d+)?)\s*%")
_DURATION = re.compile(r"\bwithin\s+(?P<count>\d+)\s+(?P<unit>hours?|days?|months?|years?)\b", re.I)
_ISO_DATE = re.compile(r"\b(20\d{2}|19\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b")
_TEXT_DATE = re.compile(
    r"\b(?:0?[1-9]|[12]\d|3[01])\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(?:20\d{2}|19\d{2})\b",
    re.I,
)


@dataclass(frozen=True)
class Candidate:
    category: str
    title: str
    value: dict[str, Any]
    confidence: Decimal
    segment: DocumentTextSegment
    quote: str


def _sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.;])\s+|\n+", text)
    return [
        re.sub(r"\s+", " ", chunk).strip()
        for chunk in chunks
        if 15 <= len(re.sub(r"\s+", " ", chunk).strip()) <= 1200
    ]


def _date_values(text: str) -> list[str]:
    values: list[str] = []
    for match in _ISO_DATE.finditer(text):
        year, month, day = match.groups()
        try:
            values.append(datetime(int(year), int(month), int(day)).date().isoformat())
        except ValueError:
            continue
    for match in _TEXT_DATE.finditer(text):
        try:
            values.append(datetime.strptime(match.group(0), "%d %B %Y").date().isoformat())
        except ValueError:
            continue
    return list(dict.fromkeys(values))


def _normalized_value(category: str, quote: str) -> dict[str, Any]:
    value: dict[str, Any] = {"text": quote}
    monies = [
        {
            "currency": match.group("currency").upper(),
            "amount": match.group("amount").replace(",", ""),
        }
        for match in _MONEY.finditer(quote)
    ]
    percentage = _PERCENTAGE.search(quote)
    duration = _DURATION.search(quote)
    dates = _date_values(quote)

    if monies:
        value["amounts"] = monies
        if category in {"insured_value", "limit"}:
            value.update(monies[0])
        if category == "deductible":
            value["minimum"] = monies[0]
    if percentage:
        value["percentage"] = percentage.group("percentage")
    if duration:
        count = int(duration.group("count"))
        unit = duration.group("unit").lower()
        value["deadline"] = {"count": count, "unit": unit}
        if unit.startswith("day"):
            value["deadline_days"] = count
        elif unit.startswith("hour"):
            value["deadline_hours"] = count
    if category == "policy_period" and dates:
        value["start_date"] = dates[0]
        if len(dates) > 1:
            value["end_date"] = dates[1]
    return value


def extract_candidates(segments: list[DocumentTextSegment]) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    for segment in segments:
        for quote in _sentences(segment.text):
            for category, pattern, confidence in _RULES:
                if not pattern.search(quote):
                    continue
                key = (category, quote.casefold())
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    Candidate(
                        category=category,
                        title=CATEGORY_TITLES[category],
                        value=_normalized_value(category, quote),
                        confidence=confidence,
                        segment=segment,
                        quote=quote,
                    )
                )
    return candidates[:250]


def run_local_policy_extraction(
    db: Session,
    *,
    claim: Claim,
    document: Document,
    user: User,
) -> PolicyExtractionResponse:
    if document.organization_id != claim.organization_id or document.claim_id != claim.id:
        raise LookupError("Document not found")
    if document.deleted_at is not None:
        raise LookupError("Document not found")
    if not document.is_current:
        raise ValueError("Only the current policy/contract document version can be extracted.")
    if (document.document_type or "").lower() not in ALLOWED_POLICY_DOCUMENT_TYPES:
        raise ValueError(
            "Classify the document as policy, policy wording, insurance contract, charter party, contract or endorsement before extraction."
        )

    segments = list(
        db.scalars(
            select(DocumentTextSegment)
            .where(
                DocumentTextSegment.organization_id == claim.organization_id,
                DocumentTextSegment.document_id == document.id,
            )
            .order_by(DocumentTextSegment.segment_index.asc())
        )
    )
    if not segments:
        raise ValueError(
            "Document text is not available yet. Complete text extraction/OCR first."
        )
    text = "\n".join(segment.text for segment in segments)
    candidates = extract_candidates(segments)
    if not candidates:
        raise ValueError(
            "No supported policy or contract terms were detected. Review the document manually."
        )

    now = datetime.now(UTC)
    run = AIRun(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        document_id=document.id,
        requested_by_id=user.id,
        task="extract_policy_contract",
        status=AIRunStatus.COMPLETED,
        provider="deterministic_local",
        model="policy-contract-rules-v1",
        prompt_name="local_policy_contract_terms",
        prompt_version="1.0",
        schema_name="policy_contract_terms_v1",
        schema_version="1.0",
        input_text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        input_char_count=len(text),
        document_type_candidate=document.document_type,
        classification_confidence=Decimal("1.000"),
        raw_output={
            "candidate_count": len(candidates),
            "categories": sorted({item.category for item in candidates}),
        },
        warnings=[
            "Deterministic candidates require human review.",
            "Issue spotting is not a coverage decision.",
        ],
        started_at=now,
        completed_at=now,
    )
    db.add(run)
    db.flush()

    rows: list[DocumentExtraction] = []
    counters: dict[str, int] = {}
    for item in candidates:
        index = counters.get(item.category, 0)
        counters[item.category] = index + 1
        row = DocumentExtraction(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            document_id=document.id,
            ai_run_id=run.id,
            source_segment_id=item.segment.id,
            field_path=f"policy.{item.category}[{index}]",
            semantic_kind=AISemanticKind.FACT,
            raw_value=item.value,
            normalized_value=item.value,
            confidence=item.confidence,
            source_locator_type=item.segment.locator_type,
            source_locator_value=item.segment.locator_value,
            source_quote=item.quote,
            source_verified=item.quote in item.segment.text,
            validation_warnings=[
                "Policy/contract term candidate; human review required.",
                "Do not treat as a coverage conclusion.",
            ],
            human_status=AIReviewStatus.PENDING,
        )
        db.add(row)
        rows.append(row)
    db.flush()

    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="EXTRACT_POLICY_CONTRACT_CANDIDATES",
        entity_type="ai_run",
        entity_id=run.id,
        new_values={
            "document_id": str(document.id),
            "candidate_count": len(rows),
            "provider": "deterministic_local",
            "external_ai_used": False,
        },
        details="Created source-linked policy/contract candidates for human review.",
    )
    db.commit()

    return PolicyExtractionResponse(
        run_id=run.id,
        claim_id=claim.id,
        document_id=document.id,
        document_name=document.original_filename,
        candidate_count=len(rows),
        candidates=[
            PolicyExtractionCandidate(
                extraction_id=row.id,
                field_path=row.field_path,
                category=row.field_path.split(".")[1].split("[")[0],
                title=CATEGORY_TITLES[row.field_path.split(".")[1].split("[")[0]],
                value=row.normalized_value,
                confidence=str(row.confidence),
                source_locator_type=row.source_locator_type,
                source_locator_value=row.source_locator_value,
                source_quote=row.source_quote or "",
                human_status=row.human_status.value,
            )
            for row in rows
        ],
    )

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.documents.models import (
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.evidence_search.models import ClaimEvidenceSearchRun, ClaimEvidenceSearchUnit
from app.modules.evidence_search.schemas import EvidenceSearchRequest
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.users.models import User

INDEX_VERSION = "12E.1"
RANKING_VERSION = "12E.1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _tokens(value: str) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for token in re.findall(r"\w+", value, flags=re.UNICODE):
        if token and token not in seen:
            seen.add(token)
            output.append(token)
    return output


def _unit_payload(
    segment: DocumentTextSegment,
    extraction: DocumentTextExtraction,
    document: Document,
) -> dict[str, Any]:
    normalized_text_hash = _hash(_normalize_text(segment.text))
    payload = {
        "organization_id": document.organization_id,
        "claim_id": document.claim_id,
        "document_id": document.id,
        "extraction_id": extraction.id,
        "segment_id": segment.id,
        "document_family_id": document.document_family_id,
        "document_version": document.version_number,
        "is_current_document": document.is_current,
        "document_type": document.document_type,
        "confidentiality_level": document.confidentiality_level.value,
        "source_file_hash": document.file_hash,
        "extraction_text_hash": extraction.text_hash,
        "normalized_text_hash": normalized_text_hash,
        "locator_type": segment.locator_type,
        "locator_value": segment.locator_value,
        "index_version": INDEX_VERSION,
    }
    payload["search_unit_hash"] = _hash(payload)
    return payload


def sync_claim_search_index(db: Session, *, claim: Claim) -> int:
    """Synchronize disposable search projections from canonical evidence rows.

    No source text is copied into the projection. Tenant and claim scope are
    mandatory SQL predicates. Superseded document segments remain indexed but
    are marked non-current so historical retrieval can be explicitly requested.
    """
    now = datetime.now(UTC)
    sources = list(
        db.execute(
            select(DocumentTextSegment, DocumentTextExtraction, Document)
            .join(DocumentTextExtraction, DocumentTextSegment.extraction_id == DocumentTextExtraction.id)
            .join(Document, DocumentTextSegment.document_id == Document.id)
            .where(
                DocumentTextSegment.organization_id == claim.organization_id,
                Document.organization_id == claim.organization_id,
                Document.claim_id == claim.id,
                Document.deleted_at.is_(None),
                Document.processing_status == DocumentProcessingStatus.PROCESSED,
                Document.malware_scan_status.notin_(
                    [
                        DocumentMalwareScanStatus.INFECTED_QUARANTINED,
                        DocumentMalwareScanStatus.SCAN_ERROR,
                    ]
                ),
            )
            .order_by(
                Document.id.asc(),
                Document.version_number.asc(),
                DocumentTextSegment.segment_index.asc(),
                DocumentTextSegment.id.asc(),
            )
        )
    )
    existing = list(
        db.scalars(
            select(ClaimEvidenceSearchUnit).where(
                ClaimEvidenceSearchUnit.organization_id == claim.organization_id,
                ClaimEvidenceSearchUnit.claim_id == claim.id,
                ClaimEvidenceSearchUnit.index_version == INDEX_VERSION,
            )
        )
    )
    by_segment = {row.segment_id: row for row in existing}
    valid_segment_ids: set[UUID] = set()
    changed = 0

    for segment, extraction, document in sources:
        valid_segment_ids.add(segment.id)
        payload = _unit_payload(segment, extraction, document)
        row = by_segment.get(segment.id)
        if row is None:
            db.add(
                ClaimEvidenceSearchUnit(
                    **payload,
                    indexed_at=now,
                    deactivated_at=None,
                )
            )
            changed += 1
            continue
        if row.search_unit_hash != payload["search_unit_hash"] or row.deactivated_at is not None:
            for key, value in payload.items():
                setattr(row, key, value)
            row.indexed_at = now
            row.deactivated_at = None
            changed += 1

    for row in existing:
        if row.segment_id not in valid_segment_ids and row.deactivated_at is None:
            row.deactivated_at = now
            changed += 1

    db.flush()
    return changed


def _snippet(text: str, normalized_query: str, tokens: list[str]) -> str:
    folded = text.casefold()
    needle = normalized_query if normalized_query and normalized_query in folded else ""
    if not needle:
        for token in tokens:
            if token in folded:
                needle = token
                break
    position = folded.find(needle) if needle else 0
    if position < 0:
        position = 0
    start = max(0, position - 180)
    end = min(len(text), start + 500)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet += "…"
    return snippet


def _score_candidate(
    *,
    text: str,
    filename: str,
    document_type: str | None,
    normalized_query: str,
    tokens: list[str],
    include_superseded: bool,
    is_current: bool,
) -> tuple[float, float, list[str]]:
    normalized_text = _normalize_text(text)
    lexical_hits = sum(min(normalized_text.count(token), 5) for token in tokens)
    lexical_score = lexical_hits / max(len(tokens), 1)
    reasons: list[str] = []
    if lexical_hits:
        reasons.append("lexical_token_match")

    phrase_bonus = 0.0
    if normalized_query and normalized_query in normalized_text:
        phrase_bonus = 3.0
        reasons.append("exact_phrase_match")

    metadata = _normalize_text(f"{filename} {document_type or ''}")
    metadata_hits = sum(1 for token in tokens if token in metadata)
    metadata_bonus = min(metadata_hits * 0.25, 1.0)
    if metadata_hits:
        reasons.append("document_metadata_match")

    current_bonus = 0.1 if include_superseded and is_current else 0.0
    if current_bonus:
        reasons.append("current_version_preference")

    return (
        round(lexical_score, 6),
        round(lexical_score + phrase_bonus + metadata_bonus + current_bonus, 6),
        reasons,
    )


def search_claim_evidence(
    db: Session,
    *,
    claim: Claim,
    user: User,
    payload: EvidenceSearchRequest,
) -> dict[str, Any]:
    started = time.perf_counter()
    sync_claim_search_index(db, claim=claim)

    normalized_query = _normalize_text(payload.query)
    tokens = _tokens(normalized_query)
    query_hash = _hash(normalized_query)
    filters = {
        "include_superseded": payload.include_superseded,
        "document_types": sorted(set(payload.document_types)),
        "document_ids": sorted(str(value) for value in set(payload.document_ids)),
        "exact_phrase": payload.exact_phrase,
    }
    filters_hash = _hash(filters)

    statement = (
        select(ClaimEvidenceSearchUnit, DocumentTextSegment, Document)
        .join(DocumentTextSegment, ClaimEvidenceSearchUnit.segment_id == DocumentTextSegment.id)
        .join(Document, ClaimEvidenceSearchUnit.document_id == Document.id)
        .where(
            ClaimEvidenceSearchUnit.organization_id == claim.organization_id,
            ClaimEvidenceSearchUnit.claim_id == claim.id,
            ClaimEvidenceSearchUnit.index_version == INDEX_VERSION,
            ClaimEvidenceSearchUnit.deactivated_at.is_(None),
            Document.organization_id == claim.organization_id,
            Document.claim_id == claim.id,
            Document.deleted_at.is_(None),
        )
    )
    if not payload.include_superseded:
        statement = statement.where(ClaimEvidenceSearchUnit.is_current_document.is_(True))
    if payload.document_types:
        statement = statement.where(ClaimEvidenceSearchUnit.document_type.in_(sorted(set(payload.document_types))))
    if payload.document_ids:
        statement = statement.where(ClaimEvidenceSearchUnit.document_id.in_(list(set(payload.document_ids))))

    lowered_text = func.lower(DocumentTextSegment.text)
    if payload.exact_phrase:
        statement = statement.where(lowered_text.contains(normalized_query, autoescape=True))
    elif tokens:
        statement = statement.where(
            or_(*[lowered_text.contains(token, autoescape=True) for token in tokens])
        )
    else:
        statement = statement.where(lowered_text.contains(normalized_query, autoescape=True))

    candidate_limit = min(max(payload.top_k * 20, 100), 1000)
    candidates = list(
        db.execute(
            statement.order_by(
                ClaimEvidenceSearchUnit.document_id.asc(),
                ClaimEvidenceSearchUnit.document_version.desc(),
                DocumentTextSegment.segment_index.asc(),
                ClaimEvidenceSearchUnit.segment_id.asc(),
            ).limit(candidate_limit)
        )
    )

    ranked: list[dict[str, Any]] = []
    for unit, segment, document in candidates:
        lexical_score, combined_score, reasons = _score_candidate(
            text=segment.text,
            filename=document.filename,
            document_type=document.document_type,
            normalized_query=normalized_query,
            tokens=tokens,
            include_superseded=payload.include_superseded,
            is_current=unit.is_current_document,
        )
        if payload.exact_phrase and "exact_phrase_match" not in reasons:
            continue
        if combined_score <= 0:
            continue
        ranked.append(
            {
                "search_unit_id": unit.id,
                "segment_id": segment.id,
                "document_id": document.id,
                "extraction_id": unit.extraction_id,
                "document_family_id": unit.document_family_id,
                "document_filename": document.filename,
                "document_type": document.document_type,
                "document_version": unit.document_version,
                "is_current_document": unit.is_current_document,
                "locator_type": unit.locator_type,
                "locator_value": unit.locator_value,
                "confidentiality_level": unit.confidentiality_level,
                "snippet": _snippet(segment.text, normalized_query, tokens),
                "lexical_score": lexical_score,
                "semantic_score": None,
                "combined_score": combined_score,
                "match_reasons": reasons,
                "source_file_hash": unit.source_file_hash,
                "extraction_text_hash": unit.extraction_text_hash,
                "normalized_text_hash": unit.normalized_text_hash,
                "search_unit_hash": unit.search_unit_hash,
            }
        )

    ranked.sort(
        key=lambda row: (
            -row["combined_score"],
            str(row["document_id"]),
            -row["document_version"],
            str(row["segment_id"]),
        )
    )
    results = ranked[: payload.top_k]
    ledger = [
        {
            "rank": index + 1,
            "search_unit_id": str(row["search_unit_id"]),
            "segment_id": str(row["segment_id"]),
            "document_id": str(row["document_id"]),
            "document_version": row["document_version"],
            "search_unit_hash": row["search_unit_hash"],
            "normalized_text_hash": row["normalized_text_hash"],
            "lexical_score": row["lexical_score"],
            "combined_score": row["combined_score"],
        }
        for index, row in enumerate(results)
    ]
    result_set_hash = _hash(
        {
            "query_hash": query_hash,
            "filters_hash": filters_hash,
            "ranking_version": RANKING_VERSION,
            "results": ledger,
        }
    )
    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    run = ClaimEvidenceSearchRun(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        requested_by_id=user.id,
        normalized_query_hash=query_hash,
        retrieval_mode=payload.retrieval_mode,
        ranking_version=RANKING_VERSION,
        filters=filters,
        filters_hash=filters_hash,
        result_ledger=ledger,
        result_set_hash=result_set_hash,
        result_count=len(results),
        latency_ms=latency_ms,
        semantic_provider=None,
        semantic_model=None,
        semantic_authorization_hash=None,
    )
    db.add(run)
    db.flush()
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="SEARCH_CLAIM_EVIDENCE",
        entity_type="claim",
        entity_id=claim.id,
        new_values={
            "search_run_id": str(run.id),
            "query_hash": query_hash,
            "filters_hash": filters_hash,
            "retrieval_mode": payload.retrieval_mode,
            "ranking_version": RANKING_VERSION,
            "result_count": len(results),
            "result_set_hash": result_set_hash,
        },
        details=(
            "Executed claim-scoped private lexical evidence retrieval. Raw query text is not persisted in the search run or audit event."
        ),
    )
    db.commit()

    return {
        "claim_id": claim.id,
        "run_id": run.id,
        "retrieval_mode": payload.retrieval_mode,
        "ranking_version": RANKING_VERSION,
        "query_hash": query_hash,
        "filters_hash": filters_hash,
        "result_set_hash": result_set_hash,
        "result_count": len(results),
        "no_sufficient_evidence_found": not results,
        "results": results,
    }

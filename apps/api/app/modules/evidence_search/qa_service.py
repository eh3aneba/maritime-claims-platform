from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.modules.claims.models import Claim
from app.modules.evidence_search.qa_schemas import ClaimQaRequest
from app.modules.evidence_search.schemas import EvidenceSearchRequest
from app.modules.evidence_search.service import search_claim_evidence
from app.modules.users.models import User

ANSWER_ENGINE_VERSION = "12F.1"
DISCLAIMER = (
    "Claim Q&A is extractive, source-linked decision support only. It does not create authoritative claim facts or determine "
    "coverage, liability, causation, recoverability, reserve, settlement, payment or legal rights. Review the cited source "
    "evidence before relying on any statement."
)

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "before", "by", "did", "do", "does", "for", "from",
    "had", "has", "have", "how", "i", "in", "is", "it", "of", "on", "or", "the", "this", "to", "was", "were",
    "what", "when", "where", "which", "who", "why", "with"
}
_NEGATION_RE = re.compile(r"\b(no|not|never|none|without|wasn't|weren't|isn't|aren't|didn't|doesn't|hadn't|hasn't)\b", re.I)
_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_NUMERIC_QUESTION_CUES = ("when", "date", "hour", "hours", "amount", "cost", "price", "interval", "how much", "how many")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    if hasattr(value, "value") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value) if value.__class__.__name__ == "UUID" else value


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _key_terms(question: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\w+", question.casefold(), flags=re.UNICODE)
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _source_ref(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "search_unit_id": row["search_unit_id"],
        "segment_id": row["segment_id"],
        "document_id": row["document_id"],
        "extraction_id": row["extraction_id"],
        "document_family_id": row["document_family_id"],
        "document_filename": row["document_filename"],
        "document_type": row["document_type"],
        "document_version": row["document_version"],
        "is_current_document": row["is_current_document"],
        "locator_type": row["locator_type"],
        "locator_value": row["locator_value"],
        "confidentiality_level": row["confidentiality_level"],
        "source_file_hash": row["source_file_hash"],
        "extraction_text_hash": row["extraction_text_hash"],
        "normalized_text_hash": row["normalized_text_hash"],
        "search_unit_hash": row["search_unit_hash"],
    }


def _statements(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in results:
        text = " ".join(str(row["snippet"]).split())
        if not text or text in seen:
            continue
        seen.add(text)
        source_refs = [_source_ref(row)]
        statement_hash = _hash({"text": text, "source_refs": source_refs})
        statements.append(
            {
                "statement_number": len(statements) + 1,
                "text": text,
                "source_refs": source_refs,
                "statement_hash": statement_hash,
            }
        )
    return statements


def _detect_conflicts(question: str, statements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(statements) < 2:
        return []
    key_terms = _key_terms(question)
    lowered_question = question.casefold()
    numeric_question = any(cue in lowered_question for cue in _NUMERIC_QUESTION_CUES)
    conflicts: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str, str]] = set()

    for index, left in enumerate(statements):
        left_text = left["text"].casefold()
        left_terms = set(re.findall(r"\w+", left_text, flags=re.UNICODE))
        for right in statements[index + 1 :]:
            right_text = right["text"].casefold()
            right_terms = set(re.findall(r"\w+", right_text, flags=re.UNICODE))
            shared = key_terms & left_terms & right_terms
            if not shared:
                continue

            left_negated = bool(_NEGATION_RE.search(left_text))
            right_negated = bool(_NEGATION_RE.search(right_text))
            if left_negated != right_negated:
                pair = tuple(sorted((left["statement_hash"], right["statement_hash"]))) + ("explicit_polarity",)
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    conflicts.append(
                        {
                            "conflict_type": "explicit_polarity",
                            "detail": "Retrieved claim-file passages express opposite positive/negative positions on shared question terms; no reconciliation was performed.",
                            "statement_hashes": [left["statement_hash"], right["statement_hash"]],
                        }
                    )
                continue

            if numeric_question:
                left_numbers = set(_NUMBER_RE.findall(left_text))
                right_numbers = set(_NUMBER_RE.findall(right_text))
                if left_numbers and right_numbers and left_numbers != right_numbers:
                    pair = tuple(sorted((left["statement_hash"], right["statement_hash"]))) + ("numeric_disagreement",)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        conflicts.append(
                            {
                                "conflict_type": "numeric_disagreement",
                                "detail": "Retrieved claim-file passages contain different numeric values relevant to the question; both sources are preserved for human review.",
                                "statement_hashes": [left["statement_hash"], right["statement_hash"]],
                            }
                        )
    return conflicts


def answer_claim_question(
    db: Session,
    *,
    claim: Claim,
    user: User,
    payload: ClaimQaRequest,
) -> dict[str, Any]:
    search = search_claim_evidence(
        db,
        claim=claim,
        user=user,
        payload=EvidenceSearchRequest(
            query=payload.question,
            top_k=payload.top_k,
            retrieval_mode=payload.retrieval_mode,
            include_superseded=payload.include_superseded,
            document_types=payload.document_types,
            document_ids=payload.document_ids,
            exact_phrase=payload.exact_phrase,
        ),
    )
    statements = _statements(list(search["results"]))
    conflicts = _detect_conflicts(payload.question, statements)

    if not statements:
        status = "insufficient_evidence"
        answer = "No sufficient evidence found in the searched claim-file passages."
        missing_evidence = ["source-linked claim-file passage supporting the question"]
    elif conflicts:
        status = "conflicting_evidence"
        answer = "The claim file contains potentially conflicting evidence. Review the source-linked statements below; the platform has not resolved the conflict."
        missing_evidence = ["human review to reconcile the conflicting source evidence"]
    else:
        status = "answered"
        # Extractive by construction: answer text contains only retrieved source passages.
        answer = "\n\n".join(statement["text"] for statement in statements)
        missing_evidence = []

    answer_hash = _hash(
        {
            "engine": ANSWER_ENGINE_VERSION,
            "question_hash": search["query_hash"],
            "result_set_hash": search["result_set_hash"],
            "status": status,
            "statement_hashes": [row["statement_hash"] for row in statements],
            "conflicts": conflicts,
            "missing_evidence": missing_evidence,
        }
    )
    return {
        "claim_id": claim.id,
        "status": status,
        "answer": answer,
        "statements": statements,
        "conflicts": conflicts,
        "missing_evidence": missing_evidence,
        "retrieval_run_id": search["run_id"],
        "retrieval_mode": search["retrieval_mode"],
        "ranking_version": search["ranking_version"],
        "question_hash": search["query_hash"],
        "result_set_hash": search["result_set_hash"],
        "semantic_used": search["semantic_used"],
        "semantic_provider": search["semantic_provider"],
        "semantic_model": search["semantic_model"],
        "semantic_authorization_hash": search["semantic_authorization_hash"],
        "answer_engine_version": ANSWER_ENGINE_VERSION,
        "answer_hash": answer_hash,
        "non_authoritative": True,
        "human_review_required": True,
        "claim_facts_updated": False,
        "disclaimer": DISCLAIMER,
    }

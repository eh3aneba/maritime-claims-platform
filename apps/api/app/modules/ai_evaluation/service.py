import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import ceil
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.ai_evaluation.models import (
    AIEvaluationCaseResult, AIEvaluationReview, AIEvaluationSuite,
)
from app.modules.ai_evaluation.schemas import AIEvaluationCaseCreate, AIEvaluationSuiteCreate
from app.modules.ai_governance.models import AIProviderActivationRequest
from app.modules.audit.service import write_audit_log
from app.modules.users.models import User

BOUNDED_REFERENCE = re.compile(
    r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
REQUIRED_BOUNDARY_SCENARIOS = {
    "prompt_injection", "malformed_input", "cross_tenant", "restricted_data",
}
TERMINAL_RETRY_STATUSES = {"failed", "review_rejected", "held", "revoked"}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _bounded_reference(value: str) -> str:
    reference = value.strip()
    if not BOUNDED_REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Evaluation evidence must use a bounded allowlisted reference")
    return reference


def _audit(db: Session, user: User, action: str, entity_id: UUID,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type="ai_evaluation_suite", entity_id=entity_id,
        new_values=values, details=details,
    )


def _activation_active(item: AIProviderActivationRequest) -> bool:
    return (item.status == "staging_authorized"
            and _as_utc(item.evaluation_expires_at) > datetime.now(UTC))


def _activation(db: Session, organization_id: UUID,
                activation_id: UUID) -> AIProviderActivationRequest:
    item = db.scalar(select(AIProviderActivationRequest).where(
        AIProviderActivationRequest.id == activation_id,
        AIProviderActivationRequest.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "AI provider activation request not found")
    return item


def _cases(db: Session, suite_id: UUID) -> list[AIEvaluationCaseResult]:
    return list(db.scalars(select(AIEvaluationCaseResult).where(
        AIEvaluationCaseResult.suite_id == suite_id,
    ).order_by(AIEvaluationCaseResult.case_key.asc())))


def _reviews(db: Session, suite_id: UUID) -> list[AIEvaluationReview]:
    return list(db.scalars(select(AIEvaluationReview).where(
        AIEvaluationReview.suite_id == suite_id,
    ).order_by(AIEvaluationReview.review_role.asc())))


def _thresholds(item: AIEvaluationSuite) -> dict:
    return {
        "min_case_count": item.min_case_count,
        "min_ce_case_count": item.min_ce_case_count,
        "min_engine_case_count": item.min_engine_case_count,
        "min_precision_bps": item.min_precision_bps,
        "min_recall_bps": item.min_recall_bps,
        "max_unsupported_rate_bps": item.max_unsupported_rate_bps,
        "min_quote_validity_bps": item.min_quote_validity_bps,
        "max_human_override_bps": item.max_human_override_bps,
        "max_p95_latency_ms": item.max_p95_latency_ms,
        "max_mean_cost_microusd": item.max_mean_cost_microusd,
        "required_boundary_scenarios": sorted(REQUIRED_BOUNDARY_SCENARIOS),
    }


def _promotion_active(db: Session, item: AIEvaluationSuite) -> bool:
    if (item.status != "staging_promoted" or item.promotion_expires_at is None
            or _as_utc(item.promotion_expires_at) <= datetime.now(UTC)):
        return False
    activation = _activation(db, item.organization_id, item.activation_request_id)
    return _activation_active(activation)


def suite_response(db: Session, item: AIEvaluationSuite) -> dict:
    cases = _cases(db, item.id)
    reviews = _reviews(db, item.id)
    review_by_role = {review.review_role: review for review in reviews}
    reviews_complete = bool(
        set(review_by_role) == {"quality", "risk"}
        and all(review.action == "approve" for review in reviews)
        and len({review.reviewer_id for review in reviews}) == 2
        and all(review.reviewer_id != item.requested_by_id for review in reviews)
    )
    return {
        "id": item.id, "activation_request_id": item.activation_request_id,
        "requested_by_id": item.requested_by_id, "finalized_by_id": item.finalized_by_id,
        "revoked_by_id": item.revoked_by_id, "attempt_number": item.attempt_number,
        "suite_key": item.suite_key, "benchmark_profile": item.benchmark_profile,
        "activation_model": item.activation_model,
        "prompt_bundle_version": item.prompt_bundle_version,
        "schema_bundle_version": item.schema_bundle_version,
        "max_input_chars": item.max_input_chars,
        "max_output_tokens": item.max_output_tokens, "data_mode": item.data_mode,
        "thresholds": _thresholds(item), "status": item.status, "outcome": item.outcome,
        "metrics": item.metrics, "failure_reasons": item.failure_reasons or [],
        "evaluation_hash": item.evaluation_hash, "evaluation_note": item.evaluation_note,
        "evaluated_at": item.evaluated_at, "decision_note": item.decision_note,
        "decision_hash": item.decision_hash, "decided_at": item.decided_at,
        "promotion_expires_at": item.promotion_expires_at,
        "revoked_at": item.revoked_at, "revocation_note": item.revocation_note,
        "cases": cases, "reviews": reviews, "created_at": item.created_at,
        "summary": {
            "case_count": len(cases), "required_case_count": item.min_case_count,
            "thresholds_passed": bool(item.metrics and item.metrics.get("overall_pass")),
            "independent_reviews_complete": reviews_complete,
            "shared_staging_promotion_recorded": item.status == "staging_promoted",
            "promotion_active": _promotion_active(db, item),
            "raw_content_stored": False, "provider_configuration_mutated": False,
            "calculated_provider_billing": False, "production_authorized": False,
            "restricted_documents_authorized": False,
            "real_claim_data_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "human_review_required": True,
        },
    }


def list_suites(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AIEvaluationSuite).where(
        AIEvaluationSuite.organization_id == organization_id,
    ).order_by(AIEvaluationSuite.created_at.desc()).limit(25)))
    return [suite_response(db, item) for item in items]


def get_suite(db: Session, organization_id: UUID, suite_id: UUID) -> AIEvaluationSuite:
    item = db.scalar(select(AIEvaluationSuite).where(
        AIEvaluationSuite.id == suite_id,
        AIEvaluationSuite.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "AI evaluation suite not found")
    return item


def create_suite(db: Session, user: User, payload: AIEvaluationSuiteCreate) -> dict:
    if not payload.confirm_content_free:
        raise HTTPException(422, "Explicit content-free benchmark confirmation is required")
    activation = _activation(db, user.organization_id, payload.activation_request_id)
    if not _activation_active(activation):
        raise HTTPException(409, "An active Sprint 11A staging authorization is required")
    attempts = list(db.scalars(select(AIEvaluationSuite).where(
        AIEvaluationSuite.activation_request_id == activation.id,
    ).order_by(AIEvaluationSuite.attempt_number.asc())))
    if attempts and attempts[-1].status not in TERMINAL_RETRY_STATUSES:
        if not (attempts[-1].status == "staging_promoted"
                and attempts[-1].promotion_expires_at is not None
                and _as_utc(attempts[-1].promotion_expires_at) <= datetime.now(UTC)):
            raise HTTPException(409, "A new evaluation requires failure, hold, revocation or expiry")
    item = AIEvaluationSuite(
        organization_id=user.organization_id, activation_request_id=activation.id,
        requested_by_id=user.id, attempt_number=len(attempts) + 1,
        suite_key=payload.suite_key.strip(), benchmark_profile="quality_safety_cost_v1",
        activation_model=activation.model,
        prompt_bundle_version=activation.prompt_bundle_version,
        schema_bundle_version=activation.schema_bundle_version,
        max_input_chars=activation.max_input_chars,
        max_output_tokens=activation.max_output_tokens,
        data_mode="synthetic_deidentified", status="collecting",
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This evaluation suite key or attempt already exists") from exc
    _audit(db, user, "CREATE_AI_EVALUATION_SUITE", item.id,
           {"activation_request_id": str(activation.id),
            "benchmark_profile": item.benchmark_profile,
            "model": item.activation_model, "thresholds": _thresholds(item),
            "raw_content_stored": False},
           "Content-free synthetic/de-identified evaluation ledger; no provider call executed.")
    db.commit(); db.refresh(item)
    return suite_response(db, item)


def record_case(db: Session, user: User, item: AIEvaluationSuite,
                payload: AIEvaluationCaseCreate) -> dict:
    if item.status != "collecting":
        raise HTTPException(409, "This evaluation suite is immutable")
    if not payload.confirm_content_free:
        raise HTTPException(422, "Explicit content-free case confirmation is required")
    if payload.executed_at.tzinfo is None or payload.executed_at.utcoffset() is None:
        raise HTTPException(422, "Case execution time must include a timezone")
    executed = payload.executed_at.astimezone(UTC)
    now = datetime.now(UTC)
    if executed > now + timedelta(minutes=5):
        raise HTTPException(422, "Case execution time cannot be in the future")
    if item.created_at and executed < _as_utc(item.created_at) - timedelta(minutes=5):
        raise HTTPException(422, "Case execution predates this evaluation suite")
    if payload.unsupported_claim_count > payload.extracted_claim_count:
        raise HTTPException(422, "Unsupported claims cannot exceed extracted claims")
    if payload.source_quote_valid_count > payload.source_quote_checked_count:
        raise HTTPException(422, "Valid source quotes cannot exceed checked quotes")
    if payload.field_true_positive + payload.field_false_positive <= 0:
        raise HTTPException(422, "Precision denominator must be positive")
    if payload.field_true_positive + payload.field_false_negative <= 0:
        raise HTTPException(422, "Recall denominator must be positive")
    if payload.extracted_claim_count <= 0 or payload.source_quote_checked_count <= 0:
        raise HTTPException(422, "Claim and source-quote denominators must be positive")
    if (payload.human_approved_count + payload.human_edited_count
            + payload.human_rejected_count <= 0):
        raise HTTPException(422, "At least one human review outcome is required")
    if payload.scenario_type in REQUIRED_BOUNDARY_SCENARIOS:
        if (payload.result == "pass") != payload.boundary_control_passed:
            raise HTTPException(422, "Boundary result and control outcome must agree")
    elif not payload.boundary_control_passed:
        raise HTTPException(422, "Baseline cases must preserve the boundary control")
    reference = _bounded_reference(payload.evidence_reference)
    snapshot = {
        "schema": "mcri-ai-evaluation-case-v1", "suite_id": str(item.id),
        "case_key": payload.case_key.strip(), "document_type": payload.document_type,
        "scenario_type": payload.scenario_type, "data_mode": payload.data_mode,
        "result": payload.result, "field_true_positive": payload.field_true_positive,
        "field_false_positive": payload.field_false_positive,
        "field_false_negative": payload.field_false_negative,
        "extracted_claim_count": payload.extracted_claim_count,
        "unsupported_claim_count": payload.unsupported_claim_count,
        "source_quote_checked_count": payload.source_quote_checked_count,
        "source_quote_valid_count": payload.source_quote_valid_count,
        "human_approved_count": payload.human_approved_count,
        "human_edited_count": payload.human_edited_count,
        "human_rejected_count": payload.human_rejected_count,
        "latency_ms": payload.latency_ms, "input_tokens": payload.input_tokens,
        "output_tokens": payload.output_tokens,
        "observed_provider_cost_microusd": payload.observed_provider_cost_microusd,
        "boundary_control_passed": payload.boundary_control_passed,
        "evidence_reference": reference, "note": payload.note.strip(),
        "executed_at": executed.isoformat(), "raw_content_stored": False,
    }
    result_hash = sha256(json.dumps(snapshot, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()
    case = AIEvaluationCaseResult(
        organization_id=user.organization_id, suite_id=item.id, submitted_by_id=user.id,
        case_key=payload.case_key.strip(), document_type=payload.document_type,
        scenario_type=payload.scenario_type, data_mode=payload.data_mode,
        result=payload.result, field_true_positive=payload.field_true_positive,
        field_false_positive=payload.field_false_positive,
        field_false_negative=payload.field_false_negative,
        extracted_claim_count=payload.extracted_claim_count,
        unsupported_claim_count=payload.unsupported_claim_count,
        source_quote_checked_count=payload.source_quote_checked_count,
        source_quote_valid_count=payload.source_quote_valid_count,
        human_approved_count=payload.human_approved_count,
        human_edited_count=payload.human_edited_count,
        human_rejected_count=payload.human_rejected_count,
        latency_ms=payload.latency_ms, input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        observed_provider_cost_microusd=payload.observed_provider_cost_microusd,
        boundary_control_passed=payload.boundary_control_passed,
        evidence_reference=reference, note=payload.note.strip(),
        result_hash=result_hash, executed_at=executed,
    )
    db.add(case)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This benchmark case key already exists") from exc
    _audit(db, user, "RECORD_AI_EVALUATION_CASE", item.id,
           {"case_id": str(case.id), "case_key": case.case_key,
            "scenario_type": case.scenario_type, "result": case.result,
            "result_hash": case.result_hash, "raw_content_stored": False},
           "Content-free aggregate benchmark result recorded. " + payload.note.strip())
    db.commit(); db.refresh(item)
    return suite_response(db, item)


def _rate_bps(numerator: int, denominator: int) -> int | None:
    return numerator * 10_000 // denominator if denominator > 0 else None


def finalize_suite(db: Session, user: User, item: AIEvaluationSuite,
                   confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit evaluation finalization is required")
    if item.status != "collecting":
        raise HTTPException(409, "This evaluation suite is immutable")
    cases = _cases(db, item.id)
    count = len(cases)
    tp = sum(case.field_true_positive for case in cases)
    fp = sum(case.field_false_positive for case in cases)
    fn = sum(case.field_false_negative for case in cases)
    extracted = sum(case.extracted_claim_count for case in cases)
    unsupported = sum(case.unsupported_claim_count for case in cases)
    quotes_checked = sum(case.source_quote_checked_count for case in cases)
    quotes_valid = sum(case.source_quote_valid_count for case in cases)
    approved = sum(case.human_approved_count for case in cases)
    edited = sum(case.human_edited_count for case in cases)
    rejected = sum(case.human_rejected_count for case in cases)
    reviewed = approved + edited + rejected
    precision = _rate_bps(tp, tp + fp)
    recall = _rate_bps(tp, tp + fn)
    unsupported_rate = _rate_bps(unsupported, extracted)
    quote_validity = _rate_bps(quotes_valid, quotes_checked)
    override_rate = _rate_bps(edited + rejected, reviewed)
    latencies = sorted(case.latency_ms for case in cases)
    p95_latency = latencies[max(ceil(0.95 * count) - 1, 0)] if count else None
    total_cost = sum(case.observed_provider_cost_microusd for case in cases)
    mean_cost = (total_cost + count - 1) // count if count else None
    ce_count = sum(case.document_type == "chief_engineer_report" for case in cases)
    engine_count = sum(case.document_type == "engine_log" for case in cases)
    scenario_pass = {
        scenario: any(case.scenario_type == scenario and case.result == "pass"
                      and case.boundary_control_passed for case in cases)
        for scenario in REQUIRED_BOUNDARY_SCENARIOS
    }
    failures: list[str] = []
    if count < item.min_case_count: failures.append("minimum_case_count")
    if ce_count < item.min_ce_case_count: failures.append("chief_engineer_report_coverage")
    if engine_count < item.min_engine_case_count: failures.append("engine_log_coverage")
    if precision is None or precision < item.min_precision_bps: failures.append("precision")
    if recall is None or recall < item.min_recall_bps: failures.append("recall")
    if (unsupported_rate is None or unsupported_rate > item.max_unsupported_rate_bps):
        failures.append("unsupported_claim_rate")
    if quote_validity is None or quote_validity < item.min_quote_validity_bps:
        failures.append("source_quote_validity")
    if override_rate is None or override_rate > item.max_human_override_bps:
        failures.append("human_override_rate")
    if p95_latency is None or p95_latency > item.max_p95_latency_ms:
        failures.append("p95_latency")
    if mean_cost is None or mean_cost > item.max_mean_cost_microusd:
        failures.append("mean_observed_provider_cost")
    if any(case.result == "fail" for case in cases): failures.append("failed_case_result")
    for scenario, passed in scenario_pass.items():
        if not passed: failures.append(f"boundary_{scenario}")
    failures = sorted(set(failures))
    metrics = {
        "overall_pass": not failures, "case_count": count,
        "chief_engineer_report_case_count": ce_count, "engine_log_case_count": engine_count,
        "field_true_positive": tp, "field_false_positive": fp, "field_false_negative": fn,
        "precision_bps": precision, "recall_bps": recall,
        "extracted_claim_count": extracted, "unsupported_claim_count": unsupported,
        "unsupported_claim_rate_bps": unsupported_rate,
        "source_quote_checked_count": quotes_checked,
        "source_quote_valid_count": quotes_valid,
        "source_quote_validity_bps": quote_validity,
        "human_reviewed_count": reviewed, "human_approved_count": approved,
        "human_edited_count": edited, "human_rejected_count": rejected,
        "human_override_rate_bps": override_rate,
        "p95_latency_ms": p95_latency,
        "total_input_tokens": sum(case.input_tokens for case in cases),
        "total_output_tokens": sum(case.output_tokens for case in cases),
        "total_observed_provider_cost_microusd": total_cost,
        "mean_observed_provider_cost_microusd": mean_cost,
        "boundary_scenarios": scenario_pass,
        "raw_content_stored": False, "calculated_provider_billing": False,
    }
    snapshot = {
        "schema": "mcri-ai-evaluation-v1", "suite_id": str(item.id),
        "activation_request_id": str(item.activation_request_id),
        "attempt_number": item.attempt_number, "benchmark_profile": item.benchmark_profile,
        "model": item.activation_model, "prompt_bundle_version": item.prompt_bundle_version,
        "schema_bundle_version": item.schema_bundle_version,
        "max_input_chars": item.max_input_chars,
        "max_output_tokens": item.max_output_tokens,
        "thresholds": _thresholds(item), "metrics": metrics,
        "failure_reasons": failures,
        "case_hashes": [case.result_hash for case in cases],
        "evaluation_note": note.strip(), "raw_content_stored": False,
        "production_authorized": False, "real_claim_data_authorized": False,
    }
    item.metrics = metrics; item.failure_reasons = failures
    item.evaluation_hash = sha256(json.dumps(snapshot, sort_keys=True,
                                              separators=(",", ":")).encode()).hexdigest()
    item.evaluation_note = note.strip(); item.evaluated_at = datetime.now(UTC)
    item.status = "failed" if failures else "review_ready"
    item.outcome = "thresholds_failed" if failures else "thresholds_passed"
    _audit(db, user, "FINALIZE_AI_EVALUATION_SUITE", item.id,
           {"status": item.status, "evaluation_hash": item.evaluation_hash,
            "metrics": metrics, "failure_reasons": failures,
            "promotion_authorized": False},
           "Deterministic threshold evaluation finalized. " + note.strip())
    db.commit(); db.refresh(item)
    return suite_response(db, item)


def record_review(db: Session, user: User, item: AIEvaluationSuite,
                  review_role: str, action: str, evidence_reference: str | None,
                  note: str) -> dict:
    if item.status not in {"review_ready", "promotion_ready"}:
        raise HTTPException(409, "Only a passing evaluation can be reviewed")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The evaluation requester cannot review this suite")
    reviews = _reviews(db, item.id)
    if any(review.review_role == review_role for review in reviews):
        raise HTTPException(409, "This review role already has a decision")
    if any(review.reviewer_id == user.id for review in reviews):
        raise HTTPException(409, "Quality and Risk reviews require different people")
    reference = _bounded_reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires a bounded review reference")
    review = AIEvaluationReview(
        organization_id=user.organization_id, suite_id=item.id, reviewer_id=user.id,
        review_role=review_role, action=action, evidence_reference=reference,
        note=note.strip(), reviewed_at=datetime.now(UTC),
    )
    db.add(review); db.flush()
    if action == "reject":
        item.status = "review_rejected"; item.outcome = "review_rejected"
        item.failure_reasons = sorted(set((item.failure_reasons or []) + [f"{review_role}_review"]))
    else:
        current = _reviews(db, item.id)
        item.status = "promotion_ready" if (
            {entry.review_role for entry in current} == {"quality", "risk"}
            and all(entry.action == "approve" for entry in current)
            and len({entry.reviewer_id for entry in current}) == 2
        ) else "review_ready"
    _audit(db, user, f"{action.upper()}_AI_EVALUATION_REVIEW", item.id,
           {"review_role": review_role, "action": action,
            "evidence_reference": reference, "status": item.status},
           "Independent AI evaluation review. " + note.strip())
    db.commit(); db.refresh(item)
    return suite_response(db, item)


def decide_promotion(db: Session, user: User, item: AIEvaluationSuite,
                     outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit promotion decision confirmation is required")
    if item.status != "promotion_ready":
        raise HTTPException(409, "Passing thresholds and two independent reviews are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The evaluation requester cannot issue final promotion")
    activation = _activation(db, user.organization_id, item.activation_request_id)
    if not _activation_active(activation):
        raise HTTPException(409, "The anchored Sprint 11A activation is no longer active")
    if (item.activation_model != activation.model
            or item.prompt_bundle_version != activation.prompt_bundle_version
            or item.schema_bundle_version != activation.schema_bundle_version
            or item.max_input_chars != activation.max_input_chars
            or item.max_output_tokens != activation.max_output_tokens):
        raise HTTPException(409, "Activation versions drifted from the evaluated bundle")
    reviews = _reviews(db, item.id)
    if (len(reviews) != 2 or len({review.reviewer_id for review in reviews}) != 2
            or any(review.action != "approve" for review in reviews)):
        raise HTTPException(409, "Quality and Risk approvals must be independent")
    expires = _as_utc(activation.evaluation_expires_at) if outcome == "promote_staging" else None
    snapshot = {
        "schema": "mcri-ai-evaluation-promotion-v1", "suite_id": str(item.id),
        "evaluation_hash": item.evaluation_hash, "activation_request_id": str(activation.id),
        "model": item.activation_model, "prompt_bundle_version": item.prompt_bundle_version,
        "schema_bundle_version": item.schema_bundle_version,
        "max_input_chars": item.max_input_chars,
        "max_output_tokens": item.max_output_tokens,
        "reviewers": [{"role": review.review_role, "reviewer_id": str(review.reviewer_id),
                       "evidence_reference": review.evidence_reference}
                      for review in reviews],
        "outcome": outcome, "decision_note": note.strip(),
        "promotion_expires_at": expires.isoformat() if expires else None,
        "provider_configuration_mutated": False, "production_authorized": False,
        "restricted_documents_authorized": False, "real_claim_data_authorized": False,
        "autonomous_claim_decisions_authorized": False, "human_review_required": True,
    }
    item.status = "staging_promoted" if outcome == "promote_staging" else "held"
    item.outcome = outcome; item.decision_note = note.strip(); item.finalized_by_id = user.id
    item.promotion_expires_at = expires; item.decided_at = datetime.now(UTC)
    item.decision_hash = sha256(json.dumps(snapshot, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    _audit(db, user, f"{outcome.upper()}_AI_EVALUATION", item.id,
           {"status": item.status, "decision_hash": item.decision_hash,
            "promotion_expires_at": expires.isoformat() if expires else None,
            "production_authorized": False, "real_claim_data_authorized": False},
           "Bounded synthetic/de-identified staging promotion decision. " + note.strip())
    db.commit(); db.refresh(item)
    return suite_response(db, item)


def revoke_promotion(db: Session, user: User, item: AIEvaluationSuite,
                     confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit promotion revocation is required")
    if item.status != "staging_promoted":
        raise HTTPException(409, "Only a promoted evaluation can be revoked")
    item.status = "revoked"; item.revoked_by_id = user.id
    item.revoked_at = datetime.now(UTC); item.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_EVALUATION_PROMOTION", item.id,
           {"status": item.status, "promotion_active": False},
           "AI evaluation promotion kill switch activated. " + note.strip())
    db.commit(); db.refresh(item)
    return suite_response(db, item)


def require_active_staging_promotion(db: Session, organization_id: UUID) -> AIEvaluationSuite:
    settings = get_settings()
    if settings.app_env.lower().strip() != "staging":
        raise HTTPException(409, "AI evaluation promotion is valid only in staging")
    item = db.scalar(select(AIEvaluationSuite).where(
        AIEvaluationSuite.organization_id == organization_id,
        AIEvaluationSuite.status == "staging_promoted",
    ).order_by(AIEvaluationSuite.created_at.desc()))
    if item is None or not _promotion_active(db, item):
        raise HTTPException(409, "No active AI evaluation promotion exists")
    if (item.activation_model != settings.ai_model
            or item.prompt_bundle_version != settings.ai_prompt_bundle_version
            or item.schema_bundle_version != settings.ai_schema_bundle_version
            or item.max_input_chars != settings.ai_max_input_chars
            or item.max_output_tokens != settings.ai_max_output_tokens):
        raise HTTPException(409, "Configured AI bundle differs from the promoted evaluation")
    return item

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.modules.ai_limited_production.models import (
    AILimitedProductionAuthorization,
    AILimitedProductionDocumentEligibility,
    AILimitedProductionIncident,
    AILimitedProductionRun,
)
from app.modules.audit.models import AuditLog
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.processing.models import (
    DocumentProcessingJob,
    ProcessingJobStatus,
    ProcessingJobType,
)
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_limited_production import _create_and_authorize, _recommended_outcome
from tests.test_ai_private_pilot import _claim_and_user
from tests.test_claims_api import login


def setup_function() -> None:
    reset_database()


def _completed_limited_production(*, safety_incident: bool = False) -> tuple[dict, list[str]]:
    _, assessment = _recommended_outcome()
    authorization = _create_and_authorize(assessment.id)
    claim, manager, alpha = _claim_and_user()
    with TestingSessionLocal() as db:
        auth = db.scalar(select(AILimitedProductionAuthorization).where(
            AILimitedProductionAuthorization.id == UUID(authorization["id"])))
        product = db.scalar(select(User).where(User.email == "alpha-product@example.com"))
        assert auth is not None and product is not None
        documents: dict[str, Document] = {}
        eligibility_ids = {}
        for workflow in ("chief_engineer_report", "engine_log"):
            document = Document(
                organization_id=alpha.id,
                claim_id=claim.id,
                uploaded_by_id=manager.id,
                document_family_id=uuid4(),
                filename=f"11f-{workflow}.txt",
                original_filename=f"11f-{workflow}.txt",
                document_type=workflow,
                mime_type="text/plain",
                file_size_bytes=512,
                file_hash=uuid4().hex * 2,
                storage_key=f"tests/11f-{workflow}.txt",
                confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
            )
            db.add(document)
            db.flush()
            eligibility = AILimitedProductionDocumentEligibility(
                organization_id=alpha.id,
                authorization_id=auth.id,
                claim_id=claim.id,
                document_id=document.id,
                attested_by_id=manager.id,
                attestation_number=1,
                rollout_bucket=0,
                document_type=workflow,
                confidentiality_level="confidential",
                legal_basis_reference=f"artifact://11f/{workflow}-legal",
                data_minimization_reference=f"artifact://11f/{workflow}-min",
                change_ticket_reference=f"ticket://11f/{workflow}",
                note="Bounded non-restricted document remained inside the completed evaluation.",
                snapshot_hash=("1" if workflow == "chief_engineer_report" else "2") * 64,
                status="eligible",
                attested_at=datetime.now(UTC),
            )
            db.add(eligibility)
            db.flush()
            eligibility_ids[workflow] = eligibility.id
            documents[workflow] = document

        run_ids: list[str] = []
        for index in range(6):
            workflow = "chief_engineer_report" if index < 3 else "engine_log"
            document = documents[workflow]
            job = DocumentProcessingJob(
                organization_id=alpha.id,
                claim_id=claim.id,
                document_id=document.id,
                requested_by_id=manager.id,
                job_type=ProcessingJobType.AI_EXTRACT_CE_REPORT,
                status=ProcessingJobStatus.COMPLETED,
                available_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                max_attempts=3,
            )
            db.add(job)
            db.flush()
            run = AILimitedProductionRun(
                organization_id=alpha.id,
                authorization_id=auth.id,
                eligibility_id=eligibility_ids[workflow],
                claim_id=claim.id,
                document_id=document.id,
                requested_by_id=manager.id,
                reviewed_by_id=product.id,
                run_key=f"11f-run-{job.id}",
                processing_job_id=job.id,
                task_type=workflow,
                status="human_reviewed",
                human_review_action="edit" if index == 0 else "approve",
                output_candidate_count=10,
                human_edit_count=1 if index == 0 else 0,
                latency_ms=2200 + index * 50,
                observed_provider_cost_microusd=120000 + index * 1000,
                evidence_reference=f"artifact://11f/run-{index}",
                note="Different human completed the limited-production review.",
                outcome_hash=f"{index + 100:064x}",
                queued_at=datetime.now(UTC),
                reviewed_at=datetime.now(UTC),
            )
            db.add(run)
            db.flush()
            run_ids.append(str(run.id))

        if safety_incident:
            db.add(AILimitedProductionIncident(
                organization_id=alpha.id,
                authorization_id=auth.id,
                reported_by_id=manager.id,
                resolved_by_id=product.id,
                severity="medium",
                category="privacy",
                evidence_reference="ticket://11f/privacy-incident",
                note="A privacy-boundary incident occurred during the completed evaluation.",
                status="resolved",
                reported_at=datetime.now(UTC),
                resolved_at=datetime.now(UTC),
                resolution_reference="artifact://11f/privacy-resolution",
                resolution_note="The incident was resolved but remains graduation-blocking evidence.",
            ))
        auth.status = "completed"
        auth.outcome = "completed"
        auth.completed_at = datetime.now(UTC)
        auth.completion_note = "Every bounded provider run was human-reviewed and monitoring passed."
        db.commit()
    return authorization, run_ids


def _create_assessment(authorization_id: str) -> dict:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    response = client.post(
        "/api/v1/ai-limited-production-outcomes/assessments",
        json={
            "authorization_id": authorization_id,
            "assessment_key": f"11f-outcome-{uuid4()}",
            "confirm_content_free_assessment": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _record_observations(assessment_id: str, run_ids: list[str]) -> None:
    for index, run_id in enumerate(run_ids):
        response = client.post(
            f"/api/v1/ai-limited-production-outcomes/assessments/{assessment_id}/observations",
            json={
                "limited_run_id": run_id,
                "usefulness_rating": 5,
                "review_seconds": 180 + index,
                "unsupported_output_count": 0,
                "source_grounded_output_count": 10,
                "source_grounding_total_count": 10,
                "workflow_completed": True,
                "evidence_reference": f"artifact://11f/outcome-observation-{index}",
                "note": "Content-free usefulness, grounding and review-effort evidence was verified.",
                "confirm_content_free_observation": True,
            },
        )
        assert response.status_code == 201, response.text


def test_11f_passing_outcome_requires_four_independent_reviews_and_never_expands_rollout() -> None:
    authorization, run_ids = _completed_limited_production()
    assessment = _create_assessment(authorization["id"])
    assert assessment["assessment_profile"] == "limited_production_graduation_v1"
    assert assessment["summary"]["production_wide_authorized"] is False
    assert assessment["summary"]["rollout_increase_authorized"] is False

    forbidden = client.post(
        f"/api/v1/ai-limited-production-outcomes/assessments/{assessment['id']}/observations",
        json={
            "limited_run_id": run_ids[0],
            "usefulness_rating": 5,
            "review_seconds": 180,
            "unsupported_output_count": 0,
            "source_grounded_output_count": 10,
            "source_grounding_total_count": 10,
            "workflow_completed": True,
            "evidence_reference": "artifact://11f/forbidden-extra",
            "note": "Raw provider content must never enter the outcome ledger.",
            "confirm_content_free_observation": True,
            "provider_response": "forbidden",
        },
    )
    assert forbidden.status_code == 422

    _record_observations(assessment["id"], run_ids)
    finalized = client.post(
        f"/api/v1/ai-limited-production-outcomes/assessments/{assessment['id']}/finalize",
        json={
            "confirm_finalize": True,
            "note": "The completed cohort has full review, grounding, cost and incident evidence.",
        },
    )
    assert finalized.status_code == 200, finalized.text
    scorecard = finalized.json()
    assert scorecard["status"] == "review_ready"
    assert scorecard["metrics"]["overall_pass"] is True
    assert scorecard["metrics"]["human_review_rate_bps"] == 10000
    assert scorecard["metrics"]["observation_coverage_rate_bps"] == 10000
    assert scorecard["metrics"]["human_edit_rate_bps"] == 1666
    assert scorecard["metrics"]["unsupported_output_rate_bps"] == 0
    assert scorecard["metrics"]["source_grounding_validity_bps"] == 10000
    assert scorecard["metrics"]["trend"]["material_regression"] is False
    assert len(scorecard["assessment_hash"]) == 64

    self_review = client.post(
        f"/api/v1/ai-limited-production-outcomes/assessments/{assessment['id']}/reviews",
        json={
            "review_role": "product",
            "action": "approve",
            "evidence_reference": "artifact://11f/self-review",
            "note": "The assessment requester must not review the graduation scorecard.",
        },
    )
    assert self_review.status_code == 409

    reviewers = [
        ("alpha-product@example.com", "product"),
        ("alpha-admin@example.com", "quality"),
        ("alpha-risk@example.com", "risk"),
        ("alpha-operations@example.com", "operations"),
    ]
    for email, role in reviewers:
        client.cookies.clear()
        login("alpha", email)
        review = client.post(
            f"/api/v1/ai-limited-production-outcomes/assessments/{assessment['id']}/reviews",
            json={
                "review_role": role,
                "action": "approve",
                "evidence_reference": f"artifact://11f/{role}-review",
                "note": f"Independent {role} reviewer reproduced the fixed 11F evidence.",
            },
        )
        assert review.status_code == 200, review.text
    assert review.json()["status"] == "decision_ready"

    client.cookies.clear()
    login("alpha", "alpha-admin@example.com")
    decided = client.post(
        f"/api/v1/ai-limited-production-outcomes/assessments/{assessment['id']}/decision",
        json={
            "outcome": "recommend_graduation_stage",
            "confirm_recommendation_only": True,
            "note": "Recommend designing a separate graduation authorization; no rollout expands here.",
        },
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "recommended"
    assert result["summary"]["graduation_stage_recommended"] is True
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["rollout_increase_authorized"] is False
    assert result["summary"]["new_document_classes_authorized"] is False
    assert len(result["decision_hash"]) == 64

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(
            AuditLog.entity_id == UUID(assessment["id"]))))
        assert {
            "CREATE_AI_LIMITED_PRODUCTION_OUTCOME_ASSESSMENT",
            "FINALIZE_AI_LIMITED_PRODUCTION_OUTCOME_ASSESSMENT",
            "DECIDE_AI_LIMITED_PRODUCTION_GRADUATION_RECOMMENDATION",
        }.issubset(actions)


def test_11f_fails_closed_on_safety_incident() -> None:
    authorization, run_ids = _completed_limited_production(safety_incident=True)
    assessment = _create_assessment(authorization["id"])
    _record_observations(assessment["id"], run_ids)
    finalized = client.post(
        f"/api/v1/ai-limited-production-outcomes/assessments/{assessment['id']}/finalize",
        json={
            "confirm_finalize": True,
            "note": "The immutable incident history must remain visible in the graduation gate.",
        },
    )
    assert finalized.status_code == 200, finalized.text
    result = finalized.json()
    assert result["status"] == "review_ready"
    assert result["metrics"]["overall_pass"] is False
    assert "privacy_security_or_cross_tenant_incident" in result["failure_reasons"]
    assert result["summary"]["production_wide_authorized"] is False

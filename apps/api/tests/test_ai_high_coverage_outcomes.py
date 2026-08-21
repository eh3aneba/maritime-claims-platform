from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.modules.ai_high_coverage.models import (
    AIHighCoverageAuthorization,
    AIHighCoverageDocumentEligibility,
    AIHighCoverageIncident,
    AIHighCoverageMonitor,
    AIHighCoverageRun,
)
from app.modules.audit.models import AuditLog
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus, ProcessingJobType
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_high_coverage import _authorize, _positive_11j
from tests.test_ai_private_pilot import _claim_and_user
from tests.test_claims_api import login


def setup_function() -> None:
    reset_database()


def _completed_high_coverage(*, safety_incident: bool = False) -> tuple[dict, list[str]]:
    authorization = _authorize(_positive_11j())
    claim, manager, alpha = _claim_and_user()
    with TestingSessionLocal() as db:
        auth = db.scalar(select(AIHighCoverageAuthorization).where(
            AIHighCoverageAuthorization.id == UUID(authorization["id"])))
        reviewer = db.scalar(select(User).where(User.email == "alpha-product@example.com"))
        assert auth is not None and reviewer is not None

        documents: dict[str, Document] = {}
        eligibility: dict[str, AIHighCoverageDocumentEligibility] = {}
        for workflow in ("chief_engineer_report", "engine_log"):
            document = Document(
                organization_id=alpha.id,
                claim_id=claim.id,
                uploaded_by_id=manager.id,
                document_family_id=uuid4(),
                filename=f"11l-{workflow}-{uuid4()}.txt",
                original_filename=f"11l-{workflow}-{uuid4()}.txt",
                document_type=workflow,
                mime_type="text/plain",
                file_size_bytes=512,
                file_hash=uuid4().hex * 2,
                storage_key=f"tests/11l-{workflow}-{uuid4()}.txt",
                confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
            )
            db.add(document)
            db.flush()
            entry = AIHighCoverageDocumentEligibility(
                organization_id=alpha.id,
                authorization_id=auth.id,
                claim_id=claim.id,
                document_id=document.id,
                attested_by_id=manager.id,
                attestation_number=1,
                rollout_bucket=0,
                document_type=workflow,
                confidentiality_level="confidential",
                legal_basis_reference=f"artifact://11l/{workflow}-legal",
                data_minimization_reference=f"artifact://11l/{workflow}-minimum",
                change_ticket_reference=f"ticket://11l/{workflow}",
                note="Persisted Sprint 11K eligibility used only as immutable Sprint 11L evidence.",
                snapshot_hash=("a" if workflow == "chief_engineer_report" else "b") * 64,
                status="eligible",
                attested_at=datetime.now(UTC),
            )
            db.add(entry)
            db.flush()
            documents[workflow] = document
            eligibility[workflow] = entry

        run_ids: list[str] = []
        for index in range(80):
            workflow = "chief_engineer_report" if index < 40 else "engine_log"
            document = documents[workflow]
            job = DocumentProcessingJob(
                organization_id=alpha.id,
                claim_id=claim.id,
                document_id=document.id,
                requested_by_id=manager.id,
                job_type=(ProcessingJobType.AI_EXTRACT_CE_REPORT
                          if workflow == "chief_engineer_report"
                          else ProcessingJobType.AI_EXTRACT_ENGINE_LOG),
                status=ProcessingJobStatus.COMPLETED,
                available_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                max_attempts=3,
            )
            db.add(job)
            db.flush()
            run = AIHighCoverageRun(
                organization_id=alpha.id,
                authorization_id=auth.id,
                eligibility_id=eligibility[workflow].id,
                claim_id=claim.id,
                document_id=document.id,
                requested_by_id=manager.id,
                reviewed_by_id=reviewer.id,
                run_key=f"11l-run-{job.id}",
                processing_job_id=job.id,
                task_type=workflow,
                status="human_reviewed",
                human_review_action="edit" if index in {0, 10, 20, 30, 40, 50, 60, 70} else "approve",
                output_candidate_count=100,
                human_edit_count=1 if index % 10 == 0 else 0,
                unsupported_output_count=0,
                source_grounded_output_count=100,
                source_grounding_total_count=100,
                latency_ms=2500,
                observed_provider_cost_microusd=100000,
                evidence_reference=f"artifact://11l/run-{index}",
                note="Different human completed the immutable Sprint 11K output review.",
                outcome_hash=f"{index + 1200:064x}",
                queued_at=datetime.now(UTC),
                reviewed_at=datetime.now(UTC),
            )
            db.add(run)
            db.flush()
            run_ids.append(str(run.id))

        db.add(AIHighCoverageMonitor(
            organization_id=alpha.id,
            authorization_id=auth.id,
            initiated_by_id=manager.id,
            monitor_key=f"11l-final-pass-{uuid4()}",
            metrics={"overall_pass": True, "provider_run_count": 80},
            failure_reasons=[],
            status="pass",
            monitor_hash="c" * 64,
            note="Fresh final Sprint 11K monitor passed before outcome assessment.",
            monitored_at=datetime.now(UTC),
        ))
        if safety_incident:
            db.add(AIHighCoverageIncident(
                organization_id=alpha.id,
                authorization_id=auth.id,
                reported_by_id=manager.id,
                resolved_by_id=reviewer.id,
                severity="medium",
                category="privacy",
                evidence_reference="ticket://11l/privacy-incident",
                note="Resolved privacy incident remains an immutable final-readiness blocker.",
                status="resolved",
                reported_at=datetime.now(UTC),
                resolved_at=datetime.now(UTC),
                resolution_reference="artifact://11l/privacy-resolution",
                resolution_note="Resolved operationally; safety history remains visible.",
            ))
        auth.status = "completed"
        auth.outcome = "completed"
        auth.completed_at = datetime.now(UTC)
        auth.completion_note = "Eighty different-human-reviewed high-coverage runs completed with a fresh passing monitor."
        auth.completion_hash = "d" * 64
        db.commit()
    return authorization, run_ids


def _create_assessment(authorization_id: str) -> dict:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    response = client.post(
        "/api/v1/ai-high-coverage-outcomes/assessments",
        json={
            "high_coverage_authorization_id": authorization_id,
            "assessment_key": f"11l-final-readiness-{uuid4()}",
            "confirm_content_free_assessment": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _observe_all(assessment_id: str, run_ids: list[str]) -> None:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    for index, run_id in enumerate(run_ids):
        response = client.post(
            f"/api/v1/ai-high-coverage-outcomes/assessments/{assessment_id}/observations",
            json={
                "high_coverage_run_id": run_id,
                "usefulness_rating": 5,
                "review_seconds": 120 + index,
                "workflow_completed": True,
                "evidence_reference": f"artifact://11l/observation-{index}",
                "note": "Content-free usefulness and review-effort evidence for the immutable Sprint 11K run.",
                "confirm_content_free_observation": True,
            },
        )
        assert response.status_code == 201, response.text


def test_11l_passing_gate_requires_eighty_runs_seven_reviews_and_never_widens_rollout() -> None:
    authorization, run_ids = _completed_high_coverage()
    assessment = _create_assessment(authorization["id"])
    assert assessment["assessment_profile"] == "high_coverage_final_readiness_v1"
    assert assessment["summary"]["production_wide_authorized"] is False
    assert assessment["summary"]["rollout_above_75_authorized"] is False

    forbidden = client.post(
        f"/api/v1/ai-high-coverage-outcomes/assessments/{assessment['id']}/observations",
        json={
            "high_coverage_run_id": run_ids[0],
            "usefulness_rating": 5,
            "review_seconds": 120,
            "workflow_completed": True,
            "evidence_reference": "artifact://11l/forbidden",
            "note": "Raw provider content is forbidden from the Sprint 11L outcome ledger.",
            "confirm_content_free_observation": True,
            "provider_response": "forbidden",
        },
    )
    assert forbidden.status_code == 422

    _observe_all(assessment["id"], run_ids)
    finalized = client.post(
        f"/api/v1/ai-high-coverage-outcomes/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "Freeze all eighty reviewed runs, observations, monitors, incidents and recovery evidence."},
    )
    assert finalized.status_code == 200, finalized.text
    scorecard = finalized.json()
    assert scorecard["status"] == "review_ready"
    assert scorecard["metrics"]["overall_pass"] is True
    assert scorecard["metrics"]["run_count"] == 80
    assert scorecard["metrics"]["human_review_rate_bps"] == 10000
    assert scorecard["metrics"]["different_human_review_rate_bps"] == 10000
    assert scorecard["metrics"]["observation_coverage_rate_bps"] == 10000
    assert scorecard["metrics"]["human_edit_rate_bps"] == 1000
    assert scorecard["metrics"]["unsupported_output_rate_bps"] == 0
    assert scorecard["metrics"]["source_grounding_validity_bps"] == 10000
    assert scorecard["metrics"]["workflow_metrics"]["chief_engineer_report"]["human_reviewed_run_count"] == 40
    assert scorecard["metrics"]["workflow_metrics"]["engine_log"]["human_reviewed_run_count"] == 40
    assert scorecard["metrics"]["rollback_recovery"]["recovery_rate_bps"] == 10000
    assert scorecard["metrics"]["monitor_history"]["latest_monitor_fresh"] is True
    assert len(scorecard["assessment_hash"]) == 64

    self_review = client.post(
        f"/api/v1/ai-high-coverage-outcomes/assessments/{assessment['id']}/reviews",
        json={"review_role": "product", "action": "approve",
              "evidence_reference": "artifact://11l/self-review",
              "note": "The requester cannot review the final-readiness package."},
    )
    assert self_review.status_code == 409

    for email, role in [
        ("alpha-product@example.com", "product"),
        ("alpha-admin@example.com", "quality"),
        ("alpha-risk@example.com", "risk"),
        ("alpha-operations@example.com", "operations"),
        ("alpha-security@example.com", "security"),
        ("alpha-governance@example.com", "claims_governance"),
        ("alpha-ai-quality@example.com", "ai_quality"),
    ]:
        client.cookies.clear()
        login("alpha", email)
        review = client.post(
            f"/api/v1/ai-high-coverage-outcomes/assessments/{assessment['id']}/reviews",
            json={"review_role": role, "action": "approve",
                  "evidence_reference": f"artifact://11l/{role}-review",
                  "note": f"Independent {role} reviewer reproduced the immutable Sprint 11L scorecard."},
        )
        assert review.status_code == 200, review.text
    assert review.json()["status"] == "decision_ready"

    client.cookies.clear()
    login("alpha", "alpha-11k-admin@example.com")
    decided = client.post(
        f"/api/v1/ai-high-coverage-outcomes/assessments/{assessment['id']}/decision",
        json={"outcome": "recommend_final_production_readiness_review",
              "confirm_recommendation_only": True,
              "note": "Recommend a separate final Production AI Readiness Review; no rollout expansion is granted."},
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "recommended"
    assert result["summary"]["final_production_readiness_review_recommended"] is True
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["rollout_above_75_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["new_document_classes_authorized"] is False
    assert len(result["decision_hash"]) == 64

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(
            AuditLog.entity_id == UUID(assessment["id"]))))
        assert {"CREATE_AI_HIGH_COVERAGE_OUTCOME_ASSESSMENT",
                "FINALIZE_AI_HIGH_COVERAGE_OUTCOME_ASSESSMENT",
                "DECIDE_AI_HIGH_COVERAGE_FINAL_READINESS_RECOMMENDATION"}.issubset(actions)


def test_11l_fails_closed_on_resolved_safety_boundary_incident() -> None:
    authorization, run_ids = _completed_high_coverage(safety_incident=True)
    assessment = _create_assessment(authorization["id"])
    _observe_all(assessment["id"], run_ids)
    finalized = client.post(
        f"/api/v1/ai-high-coverage-outcomes/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "Resolved safety incidents remain immutable blockers to final Production readiness."},
    )
    assert finalized.status_code == 200, finalized.text
    result = finalized.json()
    assert result["metrics"]["overall_pass"] is False
    assert "privacy_security_or_cross_tenant_incident" in result["failure_reasons"]
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["rollout_above_75_authorized"] is False

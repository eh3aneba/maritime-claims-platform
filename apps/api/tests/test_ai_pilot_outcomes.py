from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.ai_pilot_outcomes.models import AIPilotOutcomeAssessment
from app.modules.ai_private_pilot.models import (
    AIPrivatePilotAuthorization,
    AIPrivatePilotDocumentEligibility,
    AIPrivatePilotRun,
)
from app.modules.audit.models import AuditLog
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.organizations.models import Organization
from app.modules.processing.models import (
    DocumentProcessingJob,
    ProcessingJobStatus,
    ProcessingJobType,
)
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_private_pilot import (
    _claim_and_user,
    _create_and_authorize_pilot,
    _document,
    _promoted_evaluation,
)
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


def _completed_pilot(run_count: int = 6) -> tuple[dict, list[str]]:
    _, suite = _promoted_evaluation()
    pilot = _create_and_authorize_pilot(
        suite["id"], pilot_key=f"outcome-pilot-{run_count}-runs",
        max_provider_runs=max(8, run_count))
    claim_id, ce_document_id = _document(suffix="o")
    claim, manager, alpha = _claim_and_user()
    with TestingSessionLocal() as db:
        ce_document = db.scalar(select(Document).where(
            Document.id == UUID(ce_document_id)))
        product = db.scalar(select(User).where(User.email == "alpha-product@example.com"))
        pilot_row = db.scalar(select(AIPrivatePilotAuthorization).where(
            AIPrivatePilotAuthorization.id == UUID(pilot["id"])))
        assert ce_document is not None and product is not None and pilot_row is not None
        engine_document = Document(
            organization_id=alpha.id, claim_id=claim.id, uploaded_by_id=manager.id,
            document_family_id=uuid4(), filename="pilot-engine-outcome.txt",
            original_filename="pilot-engine-outcome.txt", document_type="engine_log",
            mime_type="text/plain", file_size_bytes=256, file_hash="e" * 64,
            storage_key="tests/pilot-engine-outcome.txt",
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )
        db.add(engine_document); db.flush()
        eligibility_by_type = {}
        for index, (workflow, document) in enumerate((
            ("chief_engineer_report", ce_document), ("engine_log", engine_document)), start=1
        ):
            eligibility = AIPrivatePilotDocumentEligibility(
                organization_id=alpha.id, pilot_id=pilot_row.id,
                claim_id=claim.id, document_id=document.id, attested_by_id=manager.id,
                attestation_number=1, document_type=workflow,
                confidentiality_level="confidential",
                authorization_basis="organization_and_data_owner",
                authorization_reference=f"artifact://ai-pilot/outcome-document-{index}",
                data_minimization_reference=f"artifact://ai-pilot/outcome-minimization-{index}",
                note="Bounded test document attestation for the outcome scorecard.",
                snapshot_hash=str(index) * 64, status="eligible",
                attested_at=datetime.now(UTC),
            )
            db.add(eligibility); db.flush(); eligibility_by_type[workflow] = eligibility
        run_ids = []
        for index in range(run_count):
            workflow = "chief_engineer_report" if index < (run_count + 1) // 2 else "engine_log"
            document = ce_document if workflow == "chief_engineer_report" else engine_document
            job = DocumentProcessingJob(
                organization_id=alpha.id, claim_id=claim.id, document_id=document.id,
                requested_by_id=manager.id,
                job_type=ProcessingJobType.AI_EXTRACT_CE_REPORT,
                status=ProcessingJobStatus.COMPLETED, available_at=datetime.now(UTC),
                completed_at=datetime.now(UTC), max_attempts=3,
            )
            db.add(job); db.flush()
            run = AIPrivatePilotRun(
                organization_id=alpha.id, pilot_id=pilot_row.id,
                eligibility_id=eligibility_by_type[workflow].id,
                claim_id=claim.id, document_id=document.id,
                requested_by_id=manager.id, reviewed_by_id=product.id,
                run_key=f"outcome-processing-{job.id}", processing_job_id=job.id,
                task_type=workflow, status="human_reviewed",
                human_review_action="edit" if index == 0 else "approve",
                output_candidate_count=5, human_edit_count=1 if index == 0 else 0,
                latency_ms=2000 + index * 100,
                observed_provider_cost_microusd=120000 + index * 1000,
                evidence_reference=f"artifact://ai-pilot/outcome-run-{index}",
                note="Different human completed the content-free pilot-run review.",
                outcome_hash=f"{index + 1:064x}", queued_at=datetime.now(UTC),
                reviewed_at=datetime.now(UTC),
            )
            db.add(run); db.flush(); run_ids.append(str(run.id))
        pilot_row.status = "completed"; pilot_row.outcome = "completed"
        pilot_row.completed_at = datetime.now(UTC)
        pilot_row.completion_note = "All bounded provider runs were independently reviewed."
        db.commit()
    return pilot, run_ids


def _create_assessment(pilot_id: str, **extra) -> dict:
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    payload = {
        "pilot_id": pilot_id, "assessment_key": f"exit-scorecard-{uuid4()}",
        "confirm_content_free_assessment": True,
    }
    payload.update(extra)
    response = client.post("/api/v1/ai-pilot-outcomes/assessments", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_passing_scorecard_requires_three_independent_reviews_and_is_recommendation_only() -> None:
    pilot, run_ids = _completed_pilot()
    assessment = _create_assessment(pilot["id"])
    assert assessment["assessment_profile"] == "private_pilot_exit_v1"
    assert assessment["summary"]["production_authorized"] is False

    raw = {
        "pilot_run_id": run_ids[0], "usefulness_rating": 5,
        "review_seconds": 180, "workflow_completed": True,
        "boundary_control_passed": True,
        "evidence_reference": "artifact://ai-pilot-outcomes/raw-rejected",
        "note": "Raw provider content must not enter the outcome assessment ledger.",
        "confirm_content_free_observation": True,
        "provider_response": "forbidden raw content",
    }
    assert client.post(
        f"/api/v1/ai-pilot-outcomes/assessments/{assessment['id']}/observations",
        json=raw).status_code == 422

    for index, run_id in enumerate(run_ids):
        response = client.post(
            f"/api/v1/ai-pilot-outcomes/assessments/{assessment['id']}/observations",
            json={
                "pilot_run_id": run_id, "usefulness_rating": 5,
                "review_seconds": 180 + index, "workflow_completed": True,
                "boundary_control_passed": True,
                "evidence_reference": f"artifact://ai-pilot-outcomes/observation-{index}",
                "note": "Content-free workflow usefulness and reviewer effort were verified.",
                "confirm_content_free_observation": True,
            },
        )
        assert response.status_code == 201, response.text
    assert response.json()["summary"]["observation_count"] == 6

    finalized = client.post(
        f"/api/v1/ai-pilot-outcomes/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "The complete workflow, cost and incident evidence is reproducible."},
    )
    assert finalized.status_code == 200, finalized.text
    scorecard = finalized.json()
    assert scorecard["status"] == "review_ready"
    assert scorecard["metrics"]["overall_pass"] is True
    assert scorecard["metrics"]["run_count"] == 6
    assert scorecard["metrics"]["chief_engineer_report_run_count"] == 3
    assert scorecard["metrics"]["engine_log_run_count"] == 3
    assert scorecard["metrics"]["human_edit_rate_bps"] == 1666
    assert scorecard["metrics"]["mean_usefulness_bps"] == 10000
    assert scorecard["metrics"]["incident_trend"]["unresolved_count"] == 0
    assert len(scorecard["assessment_hash"]) == 64

    self_review = client.post(
        f"/api/v1/ai-pilot-outcomes/assessments/{assessment['id']}/reviews",
        json={"review_role": "product", "action": "approve",
              "evidence_reference": "artifact://ai-pilot-outcomes/self-review",
              "note": "The assessment requester must not review the exit scorecard."},
    )
    assert self_review.status_code == 409

    reviewers = [
        ("alpha-product@example.com", "product"),
        ("alpha-admin@example.com", "quality"),
        ("alpha-risk@example.com", "risk"),
    ]
    for email, role in reviewers:
        client.cookies.clear(); login("alpha", email)
        review = client.post(
            f"/api/v1/ai-pilot-outcomes/assessments/{assessment['id']}/reviews",
            json={"review_role": role, "action": "approve",
                  "evidence_reference": f"artifact://ai-pilot-outcomes/{role}-review",
                  "note": f"Independent {role} reviewer reproduced the fixed exit evidence."},
        )
        assert review.status_code == 200, review.text
    assert review.json()["status"] == "decision_ready"
    assert review.json()["summary"]["independent_reviews_complete"] is True

    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    decided = client.post(
        f"/api/v1/ai-pilot-outcomes/assessments/{assessment['id']}/decision",
        json={"outcome": "recommend_limited_production_evaluation",
              "confirm_recommendation_only": True,
              "note": "Recommend designing a separate authorization; Production remains blocked."},
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "recommended"
    assert result["summary"]["limited_production_evaluation_recommended"] is True
    assert result["summary"]["production_authorized"] is False
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["authoritative_facts_auto_updated"] is False
    assert len(result["decision_hash"]) == 64

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(
            AuditLog.entity_id == UUID(assessment["id"]))))
        assert {"CREATE_AI_PILOT_OUTCOME_ASSESSMENT",
                "FINALIZE_AI_PILOT_OUTCOME_ASSESSMENT",
                "DECIDE_AI_PILOT_EXIT_RECOMMENDATION"}.issubset(actions)


def test_outcome_gate_fails_closed_and_is_tenant_scoped() -> None:
    pilot, run_ids = _completed_pilot(run_count=1)
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    extra = {
        "pilot_id": pilot["id"], "assessment_key": "raw-outcome-assessment",
        "confirm_content_free_assessment": True, "document_text": "forbidden",
    }
    assert client.post("/api/v1/ai-pilot-outcomes/assessments", json=extra).status_code == 422
    assessment = _create_assessment(pilot["id"])
    observation = client.post(
        f"/api/v1/ai-pilot-outcomes/assessments/{assessment['id']}/observations",
        json={
            "pilot_run_id": run_ids[0], "usefulness_rating": 2,
            "review_seconds": 900, "workflow_completed": False,
            "boundary_control_passed": False,
            "evidence_reference": "artifact://ai-pilot-outcomes/failing-observation",
            "note": "Workflow and safety evidence did not meet the fixed exit thresholds.",
            "confirm_content_free_observation": True,
        },
    )
    assert observation.status_code == 201
    failed = client.post(
        f"/api/v1/ai-pilot-outcomes/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "Insufficient and failing evidence must freeze as an immutable failure."},
    )
    assert failed.status_code == 200
    result = failed.json()
    assert result["status"] == "failed"
    assert {"minimum_run_count", "engine_log_coverage", "workflow_completion",
            "safety_boundary_control", "workflow_usefulness"}.issubset(
                set(result["failure_reasons"]))
    assert result["summary"]["production_authorized"] is False

    with TestingSessionLocal() as db:
        beta = db.scalar(select(Organization).where(Organization.slug == "beta"))
        assert beta is not None
        db.add(User(
            organization_id=beta.id, email="beta-outcomes@example.com",
            full_name="Beta Outcome Manager", password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_MANAGER, is_active=True))
        db.commit()
    client.cookies.clear(); login("beta", "beta-outcomes@example.com")
    dashboard = client.get("/api/v1/ai-pilot-outcomes")
    assert dashboard.status_code == 200 and dashboard.json() == {"assessments": []}
    cross_tenant = client.post(
        f"/api/v1/ai-pilot-outcomes/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "A different tenant must not access this assessment."},
    )
    assert cross_tenant.status_code == 404

    with TestingSessionLocal() as db:
        stored = db.scalar(select(AIPilotOutcomeAssessment).where(
            AIPilotOutcomeAssessment.id == UUID(assessment["id"])))
        assert stored is not None and stored.status == "failed"

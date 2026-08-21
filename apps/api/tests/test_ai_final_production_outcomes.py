from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.modules.ai_final_production.models import (
    AIFinalProductionAuthorization,
    AIFinalProductionDocumentEligibility,
    AIFinalProductionIncident,
    AIFinalProductionMonitor,
    AIFinalProductionRun,
)
from app.modules.ai_final_production_readiness.models import AIFinalProductionReadinessAssessment
from app.modules.ai_high_coverage.models import AIHighCoverageAuthorization
from app.modules.audit.models import AuditLog
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus, ProcessingJobType
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_final_production import _positive_11m
from tests.test_ai_private_pilot import _claim_and_user
from tests.test_claims_api import login


def setup_function() -> None:
    reset_database()


def _completed_final_production(*, safety_incident: bool = False) -> tuple[dict, list[str], str]:
    readiness_anchor = _positive_11m()
    claim, manager, alpha = _claim_and_user()
    with TestingSessionLocal() as db:
        readiness = db.scalar(select(AIFinalProductionReadinessAssessment).where(
            AIFinalProductionReadinessAssessment.id == UUID(readiness_anchor["id"])))
        high = db.scalar(select(AIHighCoverageAuthorization).where(
            AIHighCoverageAuthorization.id == UUID(readiness_anchor["high_id"])))
        requester = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        reviewer = db.scalar(select(User).where(User.email == "alpha-product@example.com"))
        assert readiness is not None and high is not None and requester is not None and reviewer is not None

        authorization = AIFinalProductionAuthorization(
            organization_id=alpha.id,
            readiness_assessment_id=readiness.id,
            high_coverage_outcome_assessment_id=readiness.high_coverage_outcome_assessment_id,
            high_coverage_authorization_id=high.id,
            requested_by_id=requester.id,
            finalized_by_id=reviewer.id,
            attempt_number=1,
            authorization_key=f"11o-final-production-{uuid4()}",
            environment="production",
            authorization_mode="final_production_bounded_76_90",
            readiness_assessment_hash=readiness.assessment_hash,
            readiness_decision_hash=readiness.decision_hash,
            high_coverage_outcome_assessment_hash=readiness.high_coverage_outcome_assessment_hash,
            high_coverage_outcome_decision_hash=readiness.high_coverage_outcome_decision_hash,
            high_coverage_decision_hash=readiness.high_coverage_decision_hash,
            high_coverage_completion_hash=readiness.high_coverage_completion_hash,
            broader_outcome_assessment_hash=readiness.broader_outcome_assessment_hash,
            broader_outcome_decision_hash=readiness.broader_outcome_decision_hash,
            broader_production_decision_hash=readiness.broader_production_decision_hash,
            scale_readiness_assessment_hash=readiness.readiness_assessment_hash,
            scale_readiness_decision_hash=readiness.readiness_decision_hash,
            scale_up_decision_hash=readiness.scale_up_decision_hash,
            inherited_outcome_assessment_hash=readiness.inherited_outcome_assessment_hash,
            inherited_outcome_decision_hash=readiness.inherited_outcome_decision_hash,
            model=high.model,
            prompt_bundle_version=high.prompt_bundle_version,
            schema_bundle_version=high.schema_bundle_version,
            max_input_chars=high.max_input_chars,
            max_output_tokens=high.max_output_tokens,
            allowed_document_types=["chief_engineer_report", "engine_log"],
            previous_rollout_percentage=high.rollout_percentage,
            rollout_percentage=80,
            max_claims=60,
            max_documents=180,
            max_users=60,
            max_provider_runs=900,
            starts_at=datetime.now(UTC),
            expires_at=datetime.now(UTC),
            rollback_slo_minutes=15,
            monitor_interval_minutes=60,
            max_reject_rate_bps=500,
            max_edit_rate_bps=2000,
            max_unsupported_output_rate_bps=25,
            min_source_grounding_validity_bps=9975,
            max_p95_latency_ms=15000,
            max_mean_cost_microusd=400000,
            max_quality_regression_bps=100,
            max_latency_regression_bps=750,
            max_cost_regression_bps=750,
            deployment_isolation_reference="artifact://11o/deployment",
            provider_project_reference="artifact://11o/provider",
            credential_control_reference="artifact://11o/credential",
            privacy_legal_reference="artifact://11o/privacy",
            monitoring_reference="monitor://11o/live",
            incident_response_reference="runbook://11o/incident",
            rollback_reference="runbook://11o/rollback",
            change_ticket_reference="ticket://11o/change",
            status="completed",
            outcome="completed",
            decision_note="Bounded Sprint 11N authorization approved.",
            decision_hash="3" * 64,
            decided_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            completion_note="One hundred twenty different-human-reviewed runs completed.",
            completion_hash="4" * 64,
        )
        db.add(authorization)
        db.flush()

        documents: dict[str, Document] = {}
        eligibility: dict[str, AIFinalProductionDocumentEligibility] = {}
        for workflow in ("chief_engineer_report", "engine_log"):
            document = Document(
                organization_id=alpha.id,
                claim_id=claim.id,
                uploaded_by_id=manager.id,
                document_family_id=uuid4(),
                filename=f"11o-{workflow}-{uuid4()}.txt",
                original_filename=f"11o-{workflow}-{uuid4()}.txt",
                document_type=workflow,
                mime_type="text/plain",
                file_size_bytes=512,
                file_hash=uuid4().hex * 2,
                storage_key=f"tests/11o-{workflow}-{uuid4()}.txt",
                confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
            )
            db.add(document)
            db.flush()
            entry = AIFinalProductionDocumentEligibility(
                organization_id=alpha.id,
                authorization_id=authorization.id,
                claim_id=claim.id,
                document_id=document.id,
                attested_by_id=requester.id,
                attestation_number=1,
                rollout_bucket=0,
                document_type=workflow,
                confidentiality_level="confidential",
                legal_basis_reference=f"artifact://11o/{workflow}-legal",
                data_minimization_reference=f"artifact://11o/{workflow}-minimum",
                change_ticket_reference=f"ticket://11o/{workflow}",
                note="Persisted Sprint 11N eligibility used as immutable Sprint 11O evidence.",
                snapshot_hash=("a" if workflow == "chief_engineer_report" else "b") * 64,
                status="eligible",
                attested_at=datetime.now(UTC),
            )
            db.add(entry)
            db.flush()
            documents[workflow] = document
            eligibility[workflow] = entry

        run_ids: list[str] = []
        for index in range(120):
            workflow = "chief_engineer_report" if index < 60 else "engine_log"
            document = documents[workflow]
            job = DocumentProcessingJob(
                organization_id=alpha.id,
                claim_id=claim.id,
                document_id=document.id,
                requested_by_id=requester.id,
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
            run = AIFinalProductionRun(
                organization_id=alpha.id,
                authorization_id=authorization.id,
                eligibility_id=eligibility[workflow].id,
                claim_id=claim.id,
                document_id=document.id,
                requested_by_id=requester.id,
                reviewed_by_id=reviewer.id,
                run_key=f"11o-run-{job.id}",
                processing_job_id=job.id,
                task_type=workflow,
                status="human_reviewed",
                human_review_action="edit" if index % 10 == 0 else "approve",
                output_candidate_count=100,
                human_edit_count=1 if index % 10 == 0 else 0,
                unsupported_output_count=0,
                source_grounded_output_count=100,
                source_grounding_total_count=100,
                latency_ms=2500,
                observed_provider_cost_microusd=100000,
                evidence_reference=f"artifact://11o/run-{index}",
                note="Different human completed the immutable Sprint 11N output review.",
                outcome_hash=f"{index + 2400:064x}",
                queued_at=datetime.now(UTC),
                reviewed_at=datetime.now(UTC),
            )
            db.add(run)
            db.flush()
            run_ids.append(str(run.id))

        db.add(AIFinalProductionMonitor(
            organization_id=alpha.id,
            authorization_id=authorization.id,
            initiated_by_id=requester.id,
            monitor_key=f"11o-final-pass-{uuid4()}",
            metrics={"overall_pass": True, "provider_run_count": 120},
            failure_reasons=[],
            status="pass",
            monitor_hash="5" * 64,
            note="Fresh final Sprint 11N monitor passed before outcome assessment.",
            monitored_at=datetime.now(UTC),
        ))
        if safety_incident:
            db.add(AIFinalProductionIncident(
                organization_id=alpha.id,
                authorization_id=authorization.id,
                reported_by_id=requester.id,
                resolved_by_id=reviewer.id,
                severity="medium",
                category="privacy",
                evidence_reference="ticket://11o/privacy-incident",
                note="Resolved privacy incident remains an immutable >90-readiness blocker.",
                status="resolved",
                reported_at=datetime.now(UTC),
                resolved_at=datetime.now(UTC),
                resolution_reference="artifact://11o/privacy-resolution",
                resolution_note="Resolved operationally; safety history remains visible.",
            ))
        db.commit()
        return {"id": str(authorization.id)}, run_ids, str(claim.id)


def _create_assessment(authorization_id: str) -> dict:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    response = client.post(
        "/api/v1/ai-final-production-outcomes/assessments",
        json={
            "final_production_authorization_id": authorization_id,
            "assessment_key": f"11o-over-90-readiness-{uuid4()}",
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
            f"/api/v1/ai-final-production-outcomes/assessments/{assessment_id}/observations",
            json={
                "final_production_run_id": run_id,
                "usefulness_rating": 5,
                "review_seconds": 120,
                "workflow_completed": True,
                "evidence_reference": f"artifact://11o/observation-{index}",
                "note": "Content-free usefulness and review-effort evidence for the immutable Sprint 11N run.",
                "confirm_content_free_observation": True,
            },
        )
        assert response.status_code == 201, response.text


def _business_value(assessment_id: str, claim_id: str) -> None:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    for index in range(10):
        workflow = "chief_engineer_report" if index < 5 else "engine_log"
        response = client.post(
            f"/api/v1/ai-final-production-outcomes/assessments/{assessment_id}/business-evidence",
            json={
                "claim_id": claim_id,
                "evidence_key": f"11o-business-{index}",
                "workflow_type": workflow,
                "baseline_tfta_seconds": 1000,
                "assisted_tfta_seconds": 600,
                "baseline_triage_seconds": 1000,
                "assisted_triage_seconds": 500,
                "baseline_handler_effort_seconds": 1000,
                "assisted_handler_effort_seconds": 700,
                "baseline_rework_count": 1,
                "assisted_rework_count": 1,
                "handler_usefulness_rating": 5,
                "final_claim_decision_human_owned": True,
                "evidence_reference": f"artifact://11o/business-{index}",
                "note": "Content-free higher-coverage baseline-versus-assisted claim workflow evidence.",
                "confirm_content_free_business_evidence": True,
            },
        )
        assert response.status_code == 201, response.text


def test_11o_passing_gate_requires_120_runs_business_value_ten_reviews_and_never_widens() -> None:
    authorization, run_ids, claim_id = _completed_final_production()
    assessment = _create_assessment(authorization["id"])
    assert assessment["assessment_profile"] == "final_production_outcome_v1"
    assert assessment["summary"]["rollout_above_90_authorized"] is False
    assert assessment["summary"]["production_wide_authorized"] is False

    forbidden = client.post(
        f"/api/v1/ai-final-production-outcomes/assessments/{assessment['id']}/observations",
        json={
            "final_production_run_id": run_ids[0],
            "usefulness_rating": 5,
            "review_seconds": 120,
            "workflow_completed": True,
            "evidence_reference": "artifact://11o/forbidden",
            "note": "Raw provider content is forbidden from the Sprint 11O outcome ledger.",
            "confirm_content_free_observation": True,
            "provider_response": "forbidden",
        },
    )
    assert forbidden.status_code == 422

    _observe_all(assessment["id"], run_ids)
    _business_value(assessment["id"], claim_id)
    finalized = client.post(
        f"/api/v1/ai-final-production-outcomes/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "Freeze all 120 runs, observations, business evidence, monitors, incidents and recovery evidence."},
    )
    assert finalized.status_code == 200, finalized.text
    scorecard = finalized.json()
    assert scorecard["status"] == "review_ready"
    assert scorecard["metrics"]["overall_pass"] is True
    assert scorecard["metrics"]["run_count"] == 120
    assert scorecard["metrics"]["human_review_rate_bps"] == 10000
    assert scorecard["metrics"]["different_human_review_rate_bps"] == 10000
    assert scorecard["metrics"]["observation_coverage_rate_bps"] == 10000
    assert scorecard["metrics"]["human_edit_rate_bps"] == 1000
    assert scorecard["metrics"]["unsupported_output_rate_bps"] == 0
    assert scorecard["metrics"]["source_grounding_validity_bps"] == 10000
    assert scorecard["metrics"]["workflow_metrics"]["chief_engineer_report"]["human_reviewed_run_count"] == 60
    assert scorecard["metrics"]["workflow_metrics"]["engine_log"]["human_reviewed_run_count"] == 60
    assert scorecard["metrics"]["business_value"]["workflow_count"] == 10
    assert scorecard["metrics"]["business_value"]["median_tfta_improvement_bps"] == 4000
    assert scorecard["metrics"]["business_value"]["median_triage_improvement_bps"] == 5000
    assert scorecard["metrics"]["business_value"]["median_handler_effort_improvement_bps"] == 3000
    assert scorecard["metrics"]["business_value"]["human_claim_decision_ownership_rate_bps"] == 10000
    assert scorecard["metrics"]["rollback_recovery"]["recovery_rate_bps"] == 10000
    assert scorecard["metrics"]["monitor_history"]["latest_monitor_fresh"] is True
    assert scorecard["metrics"]["source_ledger_revalidated"] is True
    assert len(scorecard["assessment_hash"]) == 64

    self_review = client.post(
        f"/api/v1/ai-final-production-outcomes/assessments/{assessment['id']}/reviews",
        json={"review_role": "product", "action": "approve",
              "evidence_reference": "artifact://11o/self-review",
              "note": "The requester cannot review the >90 readiness package."},
    )
    assert self_review.status_code == 409

    reviewers = [
        ("alpha-product@example.com", "product"),
        ("alpha-admin@example.com", "quality"),
        ("alpha-risk@example.com", "risk"),
        ("alpha-operations@example.com", "operations"),
        ("alpha-security@example.com", "security"),
        ("alpha-privacy-11n@example.com", "privacy"),
        ("alpha-governance@example.com", "claims_governance"),
        ("alpha-ai-quality@example.com", "ai_quality"),
        ("alpha-legal-11n@example.com", "legal_data_governance"),
        ("alpha-business-owner-11n@example.com", "business_owner"),
    ]
    for email, role in reviewers:
        client.cookies.clear()
        login("alpha", email)
        review = client.post(
            f"/api/v1/ai-final-production-outcomes/assessments/{assessment['id']}/reviews",
            json={"review_role": role, "action": "approve",
                  "evidence_reference": f"artifact://11o/{role}-review",
                  "note": f"Independent {role} reviewer reproduced the source-ledger Sprint 11O scorecard."},
        )
        assert review.status_code == 200, review.text
    assert review.json()["status"] == "decision_ready"

    client.cookies.clear()
    login("alpha", "alpha-11k-admin@example.com")
    decided = client.post(
        f"/api/v1/ai-final-production-outcomes/assessments/{assessment['id']}/decision",
        json={"outcome": "recommend_separate_91_100_authorization_review",
              "confirm_recommendation_only": True,
              "note": "Recommend only designing a separate 91–100% authorization review; no rollout permission is granted."},
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "recommended"
    assert result["summary"]["separate_91_100_authorization_review_recommended"] is True
    assert result["summary"]["rollout_above_90_authorized"] is False
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["new_document_classes_authorized"] is False
    assert result["summary"]["autonomous_claim_decisions_authorized"] is False
    assert result["summary"]["authoritative_facts_auto_updated"] is False
    assert len(result["decision_hash"]) == 64

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(
            AuditLog.entity_id == UUID(assessment["id"]))))
        assert {"CREATE_AI_FINAL_PRODUCTION_OUTCOME_ASSESSMENT",
                "FINALIZE_AI_FINAL_PRODUCTION_OUTCOME_ASSESSMENT",
                "DECIDE_AI_FINAL_PRODUCTION_OVER_90_READINESS"}.issubset(actions)


def test_11o_re_reads_source_incident_ledger_and_blocks_resolved_privacy_history() -> None:
    authorization, run_ids, claim_id = _completed_final_production(safety_incident=True)
    assessment = _create_assessment(authorization["id"])
    _observe_all(assessment["id"], run_ids)
    _business_value(assessment["id"], claim_id)
    finalized = client.post(
        f"/api/v1/ai-final-production-outcomes/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "Re-read source ledgers so a green aggregate monitor cannot hide resolved privacy history."},
    )
    assert finalized.status_code == 200, finalized.text
    result = finalized.json()
    assert result["metrics"]["overall_pass"] is False
    assert result["metrics"]["monitor_history"]["latest_monitor_status"] == "pass"
    assert result["metrics"]["incident_history"]["safety_boundary_incident_count"] == 1
    assert "privacy_security_or_cross_tenant_incident" in result["failure_reasons"]
    assert result["summary"]["rollout_above_90_authorized"] is False
    assert result["summary"]["production_wide_authorized"] is False

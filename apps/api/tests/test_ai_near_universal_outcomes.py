from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.ai_final_production.models import AIFinalProductionAuthorization
from app.modules.ai_final_production_outcomes.models import AIFinalProductionOutcomeAssessment
from app.modules.ai_near_universal_production.models import (
    AINearUniversalAuthorization,
    AINearUniversalDocumentEligibility,
    AINearUniversalIncident,
    AINearUniversalMonitor,
    AINearUniversalRun,
)
from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus, ProcessingJobType
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_near_universal_production import _positive_11o
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


def _add_assurance_user() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        if db.scalar(select(User).where(User.email == "alpha-assurance-11q@example.com")) is None:
            db.add(User(
                organization_id=alpha.id,
                email="alpha-assurance-11q@example.com",
                full_name="Alpha 11Q Independent Production Assurance",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.CLAIMS_MANAGER,
                is_active=True,
            ))
        db.commit()


def _completed_near_universal(*, safety_incident: bool = False) -> tuple[dict, list[str], str]:
    anchor = _positive_11o()
    _add_assurance_user()
    with TestingSessionLocal() as db:
        outcome = db.scalar(select(AIFinalProductionOutcomeAssessment).where(
            AIFinalProductionOutcomeAssessment.id == UUID(anchor["id"])))
        final = db.scalar(select(AIFinalProductionAuthorization).where(
            AIFinalProductionAuthorization.id == UUID(anchor["final_id"])))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        reviewer = db.scalar(select(User).where(User.email == "alpha-product@example.com"))
        claim = db.scalar(select(Claim).where(Claim.organization_id == outcome.organization_id)) if outcome else None
        assert outcome is not None and final is not None and manager is not None and reviewer is not None and claim is not None

        authorization = AINearUniversalAuthorization(
            organization_id=outcome.organization_id,
            outcome_assessment_id=outcome.id,
            final_production_authorization_id=final.id,
            requested_by_id=manager.id,
            finalized_by_id=reviewer.id,
            attempt_number=1,
            authorization_key=f"11q-near-universal-{uuid4()}",
            environment="production",
            authorization_mode="near_universal_bounded_91_99",
            outcome_assessment_hash=outcome.assessment_hash,
            outcome_decision_hash=outcome.decision_hash,
            final_production_decision_hash=final.decision_hash,
            final_production_completion_hash=final.completion_hash,
            final_readiness_assessment_hash=final.readiness_assessment_hash,
            final_readiness_decision_hash=final.readiness_decision_hash,
            high_coverage_outcome_assessment_hash=final.high_coverage_outcome_assessment_hash,
            high_coverage_outcome_decision_hash=final.high_coverage_outcome_decision_hash,
            high_coverage_decision_hash=final.high_coverage_decision_hash,
            high_coverage_completion_hash=final.high_coverage_completion_hash,
            broader_outcome_assessment_hash=final.broader_outcome_assessment_hash,
            broader_outcome_decision_hash=final.broader_outcome_decision_hash,
            broader_production_decision_hash=final.broader_production_decision_hash,
            scale_readiness_assessment_hash=final.scale_readiness_assessment_hash,
            scale_readiness_decision_hash=final.scale_readiness_decision_hash,
            scale_up_decision_hash=final.scale_up_decision_hash,
            inherited_outcome_assessment_hash=final.inherited_outcome_assessment_hash,
            inherited_outcome_decision_hash=final.inherited_outcome_decision_hash,
            model=final.model,
            prompt_bundle_version=final.prompt_bundle_version,
            schema_bundle_version=final.schema_bundle_version,
            max_input_chars=final.max_input_chars,
            max_output_tokens=final.max_output_tokens,
            allowed_document_types=list(outcome.allowed_document_types),
            previous_rollout_percentage=final.rollout_percentage,
            rollout_percentage=95,
            previous_max_claims=final.max_claims,
            previous_max_documents=final.max_documents,
            previous_max_users=final.max_users,
            previous_max_provider_runs=final.max_provider_runs,
            max_claims=100,
            max_documents=300,
            max_users=100,
            max_provider_runs=1800,
            starts_at=datetime.now(UTC) - timedelta(days=1),
            expires_at=datetime.now(UTC) + timedelta(days=13),
            rollback_slo_minutes=15,
            monitor_interval_minutes=60,
            max_reject_rate_bps=400,
            max_edit_rate_bps=1800,
            max_unsupported_output_rate_bps=20,
            min_source_grounding_validity_bps=9980,
            max_p95_latency_ms=14000,
            max_mean_cost_microusd=375000,
            max_quality_regression_bps=75,
            max_latency_regression_bps=500,
            max_cost_regression_bps=500,
            deployment_isolation_reference="artifact://11q/deployment",
            provider_project_reference="artifact://11q/provider",
            credential_control_reference="artifact://11q/credential",
            privacy_legal_reference="artifact://11q/privacy",
            monitoring_reference="monitor://11q/live",
            incident_response_reference="runbook://11q/incident",
            rollback_reference="runbook://11q/rollback",
            platform_reliability_reference="artifact://11q/platform-reliability",
            change_ticket_reference="ticket://11q/change",
            status="completed",
            outcome="completed",
            decision_note="Bounded Sprint 11P authorization approved.",
            decision_hash="8" * 64,
            decided_at=datetime.now(UTC) - timedelta(hours=2),
            completed_at=datetime.now(UTC) - timedelta(minutes=30),
            completion_note="One hundred sixty different-human-reviewed runs completed.",
            completion_hash="9" * 64,
        )
        db.add(authorization)
        db.flush()

        documents: dict[str, Document] = {}
        eligibility: dict[str, AINearUniversalDocumentEligibility] = {}
        for workflow in ("chief_engineer_report", "engine_log"):
            document = Document(
                organization_id=outcome.organization_id,
                claim_id=claim.id,
                uploaded_by_id=manager.id,
                document_family_id=uuid4(),
                filename=f"11q-{workflow}-{uuid4()}.txt",
                original_filename=f"11q-{workflow}-{uuid4()}.txt",
                document_type=workflow,
                mime_type="text/plain",
                file_size_bytes=512,
                file_hash=uuid4().hex * 2,
                storage_key=f"tests/11q-{workflow}-{uuid4()}.txt",
                confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
            )
            db.add(document)
            db.flush()
            entry = AINearUniversalDocumentEligibility(
                organization_id=outcome.organization_id,
                authorization_id=authorization.id,
                claim_id=claim.id,
                document_id=document.id,
                attested_by_id=manager.id,
                attestation_number=1,
                rollout_bucket=0,
                document_type=workflow,
                confidentiality_level="confidential",
                legal_basis_reference=f"artifact://11q/{workflow}-legal",
                data_minimization_reference=f"artifact://11q/{workflow}-minimum",
                change_ticket_reference=f"ticket://11q/{workflow}",
                note="Persisted Sprint 11P eligibility used as immutable Sprint 11Q evidence.",
                snapshot_hash=("a" if workflow == "chief_engineer_report" else "b") * 64,
                status="eligible",
                attested_at=datetime.now(UTC),
            )
            db.add(entry)
            db.flush()
            documents[workflow] = document
            eligibility[workflow] = entry

        run_ids: list[str] = []
        for index in range(160):
            workflow = "chief_engineer_report" if index < 80 else "engine_log"
            document = documents[workflow]
            job = DocumentProcessingJob(
                organization_id=outcome.organization_id,
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
            edited = index % 20 == 0
            run = AINearUniversalRun(
                organization_id=outcome.organization_id,
                authorization_id=authorization.id,
                eligibility_id=eligibility[workflow].id,
                claim_id=claim.id,
                document_id=document.id,
                requested_by_id=manager.id,
                reviewed_by_id=reviewer.id,
                run_key=f"11q-run-{job.id}",
                processing_job_id=job.id,
                task_type=workflow,
                status="human_reviewed",
                human_review_action="edit" if edited else "approve",
                output_candidate_count=100,
                human_edit_count=1 if edited else 0,
                unsupported_output_count=0,
                source_grounded_output_count=100,
                source_grounding_total_count=100,
                latency_ms=2000,
                observed_provider_cost_microusd=90000,
                evidence_reference=f"artifact://11q/run-{index}",
                note="Different human completed the immutable Sprint 11P output review.",
                outcome_hash=f"{index + 4000:064x}",
                queued_at=datetime.now(UTC),
                reviewed_at=datetime.now(UTC),
            )
            db.add(run)
            db.flush()
            run_ids.append(str(run.id))

        db.add(AINearUniversalMonitor(
            organization_id=outcome.organization_id,
            authorization_id=authorization.id,
            initiated_by_id=manager.id,
            monitor_key=f"11q-final-pass-{uuid4()}",
            metrics={"overall_pass": True, "provider_run_count": 160},
            failure_reasons=[],
            status="pass",
            monitor_hash="5" * 64,
            note="Fresh final Sprint 11P monitor passed before outcome assessment.",
            monitored_at=datetime.now(UTC),
        ))
        if safety_incident:
            db.add(AINearUniversalIncident(
                organization_id=outcome.organization_id,
                authorization_id=authorization.id,
                reported_by_id=manager.id,
                resolved_by_id=reviewer.id,
                severity="medium",
                category="privacy",
                evidence_reference="ticket://11q/privacy-incident",
                note="Resolved privacy incident remains an immutable 100%-readiness blocker.",
                status="resolved",
                reported_at=datetime.now(UTC) - timedelta(hours=1),
                resolved_at=datetime.now(UTC) - timedelta(minutes=40),
                resolution_reference="artifact://11q/privacy-resolution",
                resolution_note="Resolved operationally; safety history remains visible.",
            ))
        db.commit()
        return {"id": str(authorization.id)}, run_ids, str(claim.id)


def _create_assessment(authorization_id: str) -> dict:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    response = client.post(
        "/api/v1/ai-near-universal-outcomes/assessments",
        json={
            "near_universal_authorization_id": authorization_id,
            "assessment_key": f"11q-100-readiness-{uuid4()}",
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
            f"/api/v1/ai-near-universal-outcomes/assessments/{assessment_id}/observations",
            json={
                "near_universal_run_id": run_id,
                "usefulness_rating": 5,
                "review_seconds": 120,
                "workflow_completed": True,
                "evidence_reference": f"artifact://11q/observation-{index}",
                "note": "Content-free usefulness and review-effort evidence for the immutable Sprint 11P run.",
                "confirm_content_free_observation": True,
            },
        )
        assert response.status_code == 201, response.text


def _business_value(assessment_id: str, claim_id: str) -> None:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    for index in range(12):
        workflow = "chief_engineer_report" if index < 6 else "engine_log"
        response = client.post(
            f"/api/v1/ai-near-universal-outcomes/assessments/{assessment_id}/business-evidence",
            json={
                "claim_id": claim_id,
                "evidence_key": f"11q-business-{index}",
                "workflow_type": workflow,
                "baseline_tfta_seconds": 1000,
                "assisted_tfta_seconds": 600,
                "baseline_triage_seconds": 1000,
                "assisted_triage_seconds": 500,
                "baseline_handler_effort_seconds": 1000,
                "assisted_handler_effort_seconds": 700,
                "baseline_rework_count": 1,
                "assisted_rework_count": 1,
                "baseline_escalation_count": 1,
                "assisted_escalation_count": 1,
                "baseline_correction_count": 1,
                "assisted_correction_count": 1,
                "handler_usefulness_rating": 5,
                "final_claim_decision_human_owned": True,
                "evidence_reference": f"artifact://11q/business-{index}",
                "note": "Content-free near-universal baseline-versus-assisted claim workflow evidence.",
                "confirm_content_free_business_evidence": True,
            },
        )
        assert response.status_code == 201, response.text


def test_11q_passing_gate_requires_160_runs_business_value_twelve_reviews_and_never_widens() -> None:
    authorization, run_ids, claim_id = _completed_near_universal()
    assessment = _create_assessment(authorization["id"])
    assert assessment["assessment_profile"] == "near_universal_outcome_v1"
    assert assessment["summary"]["rollout_100_percent_authorized"] is False
    assert assessment["summary"]["production_wide_authorized"] is False

    forbidden = client.post(
        f"/api/v1/ai-near-universal-outcomes/assessments/{assessment['id']}/observations",
        json={
            "near_universal_run_id": run_ids[0],
            "usefulness_rating": 5,
            "review_seconds": 120,
            "workflow_completed": True,
            "evidence_reference": "artifact://11q/forbidden",
            "note": "Raw provider content is forbidden from the Sprint 11Q outcome ledger.",
            "confirm_content_free_observation": True,
            "provider_response": "forbidden",
        },
    )
    assert forbidden.status_code == 422

    _observe_all(assessment["id"], run_ids)
    _business_value(assessment["id"], claim_id)
    finalized = client.post(
        f"/api/v1/ai-near-universal-outcomes/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "Freeze all 160 runs, observations, business evidence, monitors, incidents and recovery evidence."},
    )
    assert finalized.status_code == 200, finalized.text
    scorecard = finalized.json()
    assert scorecard["status"] == "review_ready"
    assert scorecard["metrics"]["overall_pass"] is True
    assert scorecard["metrics"]["run_count"] == 160
    assert scorecard["metrics"]["human_review_rate_bps"] == 10000
    assert scorecard["metrics"]["different_human_review_rate_bps"] == 10000
    assert scorecard["metrics"]["observation_coverage_rate_bps"] == 10000
    assert scorecard["metrics"]["human_edit_rate_bps"] == 500
    assert scorecard["metrics"]["unsupported_output_rate_bps"] == 0
    assert scorecard["metrics"]["source_grounding_validity_bps"] == 10000
    assert scorecard["metrics"]["workflow_metrics"]["chief_engineer_report"]["human_reviewed_run_count"] == 80
    assert scorecard["metrics"]["workflow_metrics"]["engine_log"]["human_reviewed_run_count"] == 80
    assert scorecard["metrics"]["business_value"]["workflow_count"] == 12
    assert scorecard["metrics"]["business_value"]["median_tfta_improvement_bps"] == 4000
    assert scorecard["metrics"]["business_value"]["median_triage_improvement_bps"] == 5000
    assert scorecard["metrics"]["business_value"]["median_handler_effort_improvement_bps"] == 3000
    assert scorecard["metrics"]["business_value"]["aggregate_rework_delta"] == 0
    assert scorecard["metrics"]["business_value"]["aggregate_escalation_delta"] == 0
    assert scorecard["metrics"]["business_value"]["aggregate_correction_delta"] == 0
    assert scorecard["metrics"]["business_value"]["human_claim_decision_ownership_rate_bps"] == 10000
    assert scorecard["metrics"]["rollback_recovery"]["recovery_rate_bps"] == 10000
    assert scorecard["metrics"]["monitor_history"]["latest_monitor_fresh"] is True
    assert scorecard["metrics"]["source_ledger_revalidated"] is True
    assert len(scorecard["assessment_hash"]) == 64

    self_review = client.post(
        f"/api/v1/ai-near-universal-outcomes/assessments/{assessment['id']}/reviews",
        json={"review_role": "product", "action": "approve",
              "evidence_reference": "artifact://11q/self-review",
              "note": "The requester cannot review the 100-percent readiness package."},
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
        ("alpha-sre-11p@example.com", "platform_reliability"),
        ("alpha-assurance-11q@example.com", "independent_production_assurance"),
    ]
    for email, role in reviewers:
        client.cookies.clear()
        login("alpha", email)
        review = client.post(
            f"/api/v1/ai-near-universal-outcomes/assessments/{assessment['id']}/reviews",
            json={"review_role": role, "action": "approve",
                  "evidence_reference": f"artifact://11q/{role}-review",
                  "note": f"Independent {role} reviewer reproduced the source-ledger Sprint 11Q scorecard."},
        )
        assert review.status_code == 200, review.text
    assert review.json()["status"] == "decision_ready"

    client.cookies.clear()
    login("alpha", "alpha-11k-admin@example.com")
    decided = client.post(
        f"/api/v1/ai-near-universal-outcomes/assessments/{assessment['id']}/decision",
        json={"outcome": "recommend_separate_100_percent_authorization_review",
              "confirm_recommendation_only": True,
              "note": "Recommend only designing a separate 100-percent authorization review; no rollout permission is granted."},
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "recommended"
    assert result["summary"]["separate_100_percent_authorization_review_recommended"] is True
    assert result["summary"]["rollout_100_percent_authorized"] is False
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["new_document_classes_authorized"] is False
    assert result["summary"]["autonomous_claim_decisions_authorized"] is False
    assert result["summary"]["authoritative_facts_auto_updated"] is False
    assert len(result["decision_hash"]) == 64

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == UUID(assessment["id"]))))
        assert {"CREATE_AI_NEAR_UNIVERSAL_OUTCOME_ASSESSMENT",
                "FINALIZE_AI_NEAR_UNIVERSAL_OUTCOME_ASSESSMENT",
                "DECIDE_AI_NEAR_UNIVERSAL_100_PERCENT_READINESS"}.issubset(actions)


def test_11q_re_reads_source_incident_ledger_and_blocks_resolved_privacy_history() -> None:
    authorization, run_ids, claim_id = _completed_near_universal(safety_incident=True)
    assessment = _create_assessment(authorization["id"])
    _observe_all(assessment["id"], run_ids)
    _business_value(assessment["id"], claim_id)
    finalized = client.post(
        f"/api/v1/ai-near-universal-outcomes/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "Re-read source ledgers so a green aggregate monitor cannot hide resolved privacy history."},
    )
    assert finalized.status_code == 200, finalized.text
    result = finalized.json()
    assert result["metrics"]["overall_pass"] is False
    assert result["metrics"]["monitor_history"]["latest_monitor_status"] == "pass"
    assert result["metrics"]["incident_history"]["safety_boundary_incident_count"] == 1
    assert "privacy_security_or_cross_tenant_incident" in result["failure_reasons"]
    assert result["summary"]["rollout_100_percent_authorized"] is False
    assert result["summary"]["production_wide_authorized"] is False

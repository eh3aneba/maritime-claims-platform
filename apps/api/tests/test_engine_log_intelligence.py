from datetime import date
from io import BytesIO
from pathlib import Path
from uuid import UUID

from openpyxl import Workbook
from sqlalchemy import select

from app.ai.gateway.base import AIRequest, AIResponse
from app.core.security import hash_password
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents import service as document_service
from app.modules.documents.models import Document
from app.modules.intelligence.models import AIRunStatus, AISemanticKind, AIReviewStatus, DocumentExtraction
from app.modules.intelligence.service import get_engine_log_event_candidates, run_engine_log_intelligence
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobType
from app.modules.processing.service import claim_next_job, enqueue_processing_job, process_job
from app.modules.review.service import review_extraction
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database

PASSWORD = "Strong-EngineLog-Test-2026"


class FakeEngineLogProvider:
    name = "fake"
    _model = "fake-engine-log-v1"

    def __init__(self, *, classification: str = "engine_log", bad_quote: bool = False) -> None:
        self.classification = classification
        self.bad_quote = bad_quote
        self.last_request: AIRequest | None = None

    def generate(self, request: AIRequest) -> AIResponse:
        self.last_request = request
        row1 = "not present in source" if self.bad_quote else "2026-07-10 | 10:52 | 620 rpm | 75% | 18500 rpm | 510 C | 3.8 bar | High vibration alarm | Reduced load"
        row2 = "2026-07-10 | 11:05 | 0 rpm | 0% | 0 rpm | 420 C | 3.9 bar | Main engine shutdown | Turbocharger isolated"
        payload = {
            "classification": {"document_type": self.classification, "confidence": 0.99},
            "identification": {
                "vessel_name": ss("MT ORION", "MT ORION"),
                "imo_number": ss(None, None, 0),
                "log_date": ss("2026-07-10", "Log date: 2026-07-10"),
                "engine_or_equipment": ss("Main Engine / Turbocharger No.2", "Main Engine / Turbocharger No.2"),
            },
            "events": [
                {
                    "date": ss("2026-07-10", row1),
                    "time": ss("10:52", row1),
                    "timezone": ss(None, None, 0),
                    "event_type": ss("alarm", row1, 0.92),
                    "rpm": ss("620 rpm", row1),
                    "engine_load": ss("75%", row1),
                    "turbocharger_speed": ss("18500 rpm", row1),
                    "exhaust_temperature": ss("510 C", row1),
                    "lube_oil_pressure": ss("3.8 bar", row1),
                    "alarm": ss("High vibration alarm", row1),
                    "shutdown": sb(None, None, 0),
                    "restart": sb(None, None, 0),
                    "action": ss("Reduced load", row1),
                    "remarks": ss(None, None, 0),
                },
                {
                    "date": ss("2026-07-10", row2),
                    "time": ss("11:05", row2),
                    "timezone": ss(None, None, 0),
                    "event_type": ss("shutdown", row2, 0.95),
                    "rpm": ss("0 rpm", row2),
                    "engine_load": ss("0%", row2),
                    "turbocharger_speed": ss("0 rpm", row2),
                    "exhaust_temperature": ss("420 C", row2),
                    "lube_oil_pressure": ss("3.9 bar", row2),
                    "alarm": ss("Main engine shutdown", row2),
                    "shutdown": sb(True, row2),
                    "restart": sb(None, None, 0),
                    "action": ss("Turbocharger isolated", row2),
                    "remarks": ss(None, None, 0),
                },
            ],
        }
        if self.classification != "engine_log":
            payload["events"] = []
        return AIResponse(
            provider=self.name,
            model=self._model,
            structured_output=payload,
            output_text="{}",
            usage={"input_tokens": 120, "output_tokens": 90, "total_tokens": 210},
            raw_response_id="resp_engine_log_001",
        )


def ss(value, quote, confidence: float = 0.96) -> dict:
    return {"value": value, "confidence": confidence, "source": {"segment_index": 0 if value is not None else None, "quote": quote}}


def sb(value, quote, confidence: float = 0.96) -> dict:
    return {"value": value, "confidence": confidence, "source": {"segment_index": 0 if value is not None else None, "quote": quote}}


def setup_function() -> None:
    reset_database()


def configure_storage(tmp_path: Path) -> None:
    document_service.settings.local_storage_path = str(tmp_path / "documents")
    document_service.settings.max_upload_mb = 2


def make_engine_log_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Engine Log"
    sheet.append(["MT ORION"])
    sheet.append(["Log date: 2026-07-10"])
    sheet.append(["Main Engine / Turbocharger No.2"])
    sheet.append(["Date", "Time", "RPM", "Load", "TC Speed", "Exh Temp", "LO Pressure", "Alarm", "Action"])
    sheet.append(["2026-07-10", "10:52", "620 rpm", "75%", "18500 rpm", "510 C", "3.8 bar", "High vibration alarm", "Reduced load"])
    sheet.append(["2026-07-10", "11:05", "0 rpm", "0%", "0 rpm", "420 C", "3.9 bar", "Main engine shutdown", "Turbocharger isolated"])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def seed_claim() -> dict[str, str]:
    with TestingSessionLocal() as db:
        alpha = Organization(name="Alpha Marine", slug="alpha")
        beta = Organization(name="Beta Marine", slug="beta")
        db.add_all([alpha, beta])
        db.flush()
        alpha_user = User(
            organization_id=alpha.id,
            email="alpha@example.com",
            full_name="Alpha Handler",
            password_hash=hash_password(PASSWORD),
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        beta_user = User(
            organization_id=beta.id,
            email="beta@example.com",
            full_name="Beta Handler",
            password_hash=hash_password(PASSWORD),
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        vessel = Vessel(organization_id=alpha.id, name="MT ORION", imo_number="7000301")
        db.add_all([alpha_user, beta_user, vessel])
        db.flush()
        claim = Claim(
            organization_id=alpha.id,
            vessel_id=vessel.id,
            claim_reference="MCRI-HM-2026-0001",
            incident_date=date(2026, 7, 10),
            notification_date=date(2026, 7, 11),
            incident_description="Turbocharger failure",
            currency="USD",
        )
        db.add(claim)
        db.commit()
        return {"claim_id": str(claim.id), "org_id": str(alpha.id), "user_id": str(alpha_user.id)}


def login(slug: str, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"organization_slug": slug, "email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def upload_and_extract_text(tmp_path: Path, ids: dict[str, str]) -> UUID:
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    upload = client.post(
        f"/api/v1/claims/{ids['claim_id']}/documents",
        files={
            "file": (
                "Engine_Log.xlsx",
                make_engine_log_xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"document_type": "engine_log"},
    )
    assert upload.status_code == 201, upload.text
    document_id = UUID(upload.json()["id"])
    with TestingSessionLocal() as db:
        job = claim_next_job(db, worker_id="text-worker")
        assert job is not None and job.job_type == ProcessingJobType.EXTRACT_TEXT
        process_job(db, job=job)
    return document_id


def test_engine_log_ai_run_persists_row_granular_source_linked_events(tmp_path: Path) -> None:
    ids = seed_claim()
    document_id = upload_and_extract_text(tmp_path, ids)
    provider = FakeEngineLogProvider()

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        run = run_engine_log_intelligence(db, document=document, requested_by_id=None, provider=provider)
        assert run.status == AIRunStatus.COMPLETED
        assert run.task == "engine_log_extract"
        assert run.schema_name == "engine_log_v1"
        assert run.document_type_candidate == "engine_log"

        rows = list(db.scalars(select(DocumentExtraction).where(DocumentExtraction.ai_run_id == run.id)))
        by_path = {row.field_path: row for row in rows}
        assert by_path["engine_log.events[0].time"].normalized_value == "10:52"
        assert by_path["engine_log.events[0].event_type"].semantic_kind == AISemanticKind.INFERENCE
        assert by_path["engine_log.events[0].alarm"].semantic_kind == AISemanticKind.FACT
        assert by_path["engine_log.events[0].alarm"].source_verified is True
        assert by_path["engine_log.events[0].rpm"].normalized_value == {"value": 620.0, "unit": "rpm", "raw": "620 rpm"}
        assert by_path["engine_log.events[0].lube_oil_pressure"].normalized_value == {"value": 3.8, "unit": "bar", "raw": "3.8 bar"}
        assert by_path["engine_log.events[1].shutdown"].raw_value is True

        event_run, events = get_engine_log_event_candidates(db, document_id=document.id, organization_id=document.organization_id)
        assert event_run is not None and event_run.id == run.id
        assert len(events) == 2
        assert events[0]["timestamp_candidate"]["time"] == "10:52"
        assert events[0]["values"]["alarm"] == "High vibration alarm"
        assert events[0]["human_review_complete"] is False

    assert provider.last_request is not None
    assert provider.last_request.schema_name == "engine_log_v1"
    assert "preserve the log's row/event granularity" in provider.last_request.system_instructions.lower()
    assert "Engine Log" in provider.last_request.input_text


def test_engine_log_event_evidence_is_reviewable_but_not_promoted_to_scalar_claim_facts(tmp_path: Path) -> None:
    ids = seed_claim()
    document_id = upload_and_extract_text(tmp_path, ids)
    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        run = run_engine_log_intelligence(db, document=document, requested_by_id=None, provider=FakeEngineLogProvider())
        extraction = db.scalar(
            select(DocumentExtraction).where(
                DocumentExtraction.ai_run_id == run.id,
                DocumentExtraction.field_path == "engine_log.events[0].time",
            )
        )
        reviewer = db.get(User, UUID(ids["user_id"]))
        reviewed, claim_fact, promoted = review_extraction(
            db, extraction=extraction, reviewer=reviewer, action="approve"
        )
        db.commit()
        assert reviewed.human_status == AIReviewStatus.APPROVED
        assert promoted is False
        assert claim_fact is None
        assert db.scalar(select(ClaimFact).where(ClaimFact.claim_id == document.claim_id, ClaimFact.field_path == extraction.field_path)) is None


def test_engine_log_bad_source_quote_is_flagged(tmp_path: Path) -> None:
    ids = seed_claim()
    document_id = upload_and_extract_text(tmp_path, ids)
    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        run = run_engine_log_intelligence(db, document=document, requested_by_id=None, provider=FakeEngineLogProvider(bad_quote=True))
        row = db.scalar(
            select(DocumentExtraction).where(
                DocumentExtraction.ai_run_id == run.id,
                DocumentExtraction.field_path == "engine_log.events[0].time",
            )
        )
        assert row.source_verified is False
        assert any("could not be verified" in warning for warning in (row.validation_warnings or []))


def test_non_engine_log_classification_does_not_persist_event_rows(tmp_path: Path) -> None:
    ids = seed_claim()
    document_id = upload_and_extract_text(tmp_path, ids)
    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        run = run_engine_log_intelligence(db, document=document, requested_by_id=None, provider=FakeEngineLogProvider(classification="other"))
        assert run.document_type_candidate == "other"
        rows = list(db.scalars(select(DocumentExtraction).where(DocumentExtraction.ai_run_id == run.id)))
        assert rows == []
        assert any("not classified as engine_log" in warning for warning in (run.warnings or []))


def test_engine_log_background_job_dispatches_to_ai_pipeline(tmp_path: Path, monkeypatch) -> None:
    ids = seed_claim()
    document_id = upload_and_extract_text(tmp_path, ids)
    provider = FakeEngineLogProvider()
    monkeypatch.setattr("app.modules.intelligence.service.get_ai_provider", lambda: provider)

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        enqueue_processing_job(
            db,
            document=document,
            requested_by_id=None,
            job_type=ProcessingJobType.AI_EXTRACT_ENGINE_LOG,
        )
        db.commit()
        job = claim_next_job(db, worker_id="engine-ai-worker")
        assert job is not None and job.job_type == ProcessingJobType.AI_EXTRACT_ENGINE_LOG
        process_job(db, job=job)
        db.refresh(job)
        assert job.status.value == "completed"
        assert job.result["classification"] == "engine_log"


def test_engine_log_events_endpoint_is_tenant_scoped(tmp_path: Path) -> None:
    ids = seed_claim()
    document_id = upload_and_extract_text(tmp_path, ids)
    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        run_engine_log_intelligence(db, document=document, requested_by_id=None, provider=FakeEngineLogProvider())

    login("alpha", "alpha@example.com")
    own = client.get(f"/api/v1/claims/{ids['claim_id']}/documents/{document_id}/intelligence/engine-log/events")
    assert own.status_code == 200, own.text
    assert len(own.json()["events"]) == 2

    login("beta", "beta@example.com")
    other = client.get(f"/api/v1/claims/{ids['claim_id']}/documents/{document_id}/intelligence/engine-log/events")
    assert other.status_code == 404


def test_engine_log_enqueue_endpoint_creates_background_job(tmp_path: Path, monkeypatch) -> None:
    ids = seed_claim()
    document_id = upload_and_extract_text(tmp_path, ids)
    provider = FakeEngineLogProvider()
    monkeypatch.setattr("app.modules.intelligence.router.get_ai_provider", lambda: provider)

    response = client.post(
        f"/api/v1/claims/{ids['claim_id']}/documents/{document_id}/intelligence/engine-log"
    )
    assert response.status_code == 202, response.text
    with TestingSessionLocal() as db:
        job = db.scalar(
            select(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.document_id == document_id,
                DocumentProcessingJob.job_type == ProcessingJobType.AI_EXTRACT_ENGINE_LOG,
            )
            .order_by(DocumentProcessingJob.created_at.desc())
        )
        assert job is not None
        assert str(job.id) == response.json()["job_id"]


def test_restricted_engine_log_blocks_external_ai_without_explicit_opt_in(tmp_path: Path, monkeypatch) -> None:
    ids = seed_claim()
    document_id = upload_and_extract_text(tmp_path, ids)

    class ExternalProvider:
        name = "openai"

    monkeypatch.setattr("app.modules.intelligence.router.get_ai_provider", lambda: ExternalProvider())
    monkeypatch.setattr("app.modules.intelligence.router.settings.allow_external_ai_restricted", False)
    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        from app.modules.documents.models import ConfidentialityLevel
        document.confidentiality_level = ConfidentialityLevel.RESTRICTED
        db.commit()

    response = client.post(
        f"/api/v1/claims/{ids['claim_id']}/documents/{document_id}/intelligence/engine-log"
    )
    assert response.status_code == 409
    assert "Restricted documents" in response.json()["detail"]


def test_engine_log_schema_is_strict_and_requires_event_fields() -> None:
    from app.ai.schemas.engine_log import EngineLogExtraction

    schema = EngineLogExtraction.model_json_schema()
    assert set(schema["required"]) == {"classification", "identification", "events"}
    assert schema["additionalProperties"] is False
    event_schema = schema["$defs"]["EngineLogEvent"]
    assert event_schema["additionalProperties"] is False
    assert set(event_schema["required"]) == {
        "date", "time", "timezone", "event_type", "rpm", "engine_load",
        "turbocharger_speed", "exhaust_temperature", "lube_oil_pressure",
        "alarm", "shutdown", "restart", "action", "remarks",
    }

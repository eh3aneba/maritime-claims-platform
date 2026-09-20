from datetime import UTC, datetime
import hashlib
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_models import (
    ExternalDocumentSourceDueTickDispatchConsumption,
    ExternalDocumentSourceDueTickDispatchConsumptionReceipt,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
    ensure_due_tick_dispatch_consumption_integrity,
)
from app.modules.external_document_sources.due_tick_dispatch_models import (
    ExternalDocumentSourceDueTickDispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    dispatch_next_due_tick,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
    ExternalDocumentSourceDueTickObservationReceipt,
)
from app.modules.external_document_sources.due_tick_observation_service import (
    execute_due_tick_observation,
)
from app.modules.processing.models import DocumentProcessingJob
from app.workers import external_evidence_observation_worker as observation_worker
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_external_document_source_change_detection import _ChangeAdapter
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_family_version_admission import _bound_v1
from tests.test_external_document_source_generation_3_change_detection import (
    _baseline_projection,
)
from tests.test_external_document_source_recurring_observation_schedule import (
    _authorize as _authorize_schedule,
    _mfa_headers,
)


def setup_function() -> None:
    _phase_y_setup()
    reset_database()


def teardown_function() -> None:
    _phase_y_teardown()


def _prepare(monkeypatch, suffix: str):
    actor_id, profile_id, _claim_id, initial_execution, binding = _bound_v1(
        monkeypatch,
        suffix,
    )
    response = _authorize_schedule(
        profile_id,
        binding["id"],
        actor_id,
        key=f"phase-ae-{suffix}-schedule",
        cadence="hourly",
        effective_at="2026-09-20T00:00:00Z",
        headers=_mfa_headers(actor_id),
    )
    assert response.status_code == 201, response.text
    schedule_id = UUID(response.json()["id"])

    adapter = _ChangeAdapter()
    adapter.result = ExactItemMetadataResult(
        found=True,
        item=_baseline_projection(),
    )
    register_external_document_source_change_detection_adapter(
        "sharepoint",
        "graph_drive_item_metadata_read_v1",
        adapter,
    )

    with TestingSessionLocal() as db:
        dispatch = dispatch_next_due_tick(
            db,
            worker_id=f"phase-ae-{suffix}-scheduler",
            now=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        )
        assert dispatch is not None
        dispatch_id = dispatch.id

    return (
        actor_id,
        UUID(profile_id),
        schedule_id,
        UUID(binding["organization_id"]),
        UUID(initial_execution["document_id"]),
        dispatch_id,
        adapter,
    )


def test_phase_ae_consumes_dispatch_with_service_identity_and_no_human_user(
    monkeypatch,
) -> None:
    (
        _actor_id,
        _profile_id,
        _schedule_id,
        _organization_id,
        document_id,
        dispatch_id,
        adapter,
    ) = _prepare(monkeypatch, "service")

    service_id = "external-evidence-observer-v1"
    service_hash = hashlib.sha256(service_id.encode("utf-8")).hexdigest()

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        original_document = (
            document.is_current,
            document.version_number,
            document.file_hash,
            document.processing_status,
        )
        jobs_before = db.query(DocumentProcessingJob).count()

        observation, consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id=service_id,
            now=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        )
        assert outcome == "consumed"
        assert observation.actor_kind == "service"
        assert observation.executed_by_id is None
        assert observation.service_executor_id_hash == service_hash
        assert observation.result_status == "unchanged"
        assert consumption.status == "executed"
        assert consumption.service_executor_id_hash == service_hash
        assert consumption.observation_execution_id == observation.id
        ensure_due_tick_dispatch_consumption_integrity(db, consumption)

        receipt = db.query(ExternalDocumentSourceDueTickObservationReceipt).one()
        assert receipt.actor_kind == "service"
        assert receipt.actor_id is None
        assert receipt.service_executor_id_hash == service_hash

        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumptionReceipt).count() == 1
        assert db.query(DocumentProcessingJob).count() == jobs_before

        unchanged = db.get(Document, document_id)
        assert unchanged is not None
        assert (
            unchanged.is_current,
            unchanged.version_number,
            unchanged.file_hash,
            unchanged.processing_status,
        ) == original_document

        audit = (
            db.query(AuditLog)
            .filter(AuditLog.action == "CONSUME_EXTERNAL_EVIDENCE_DUE_TICK_DISPATCH")
            .one()
        )
        assert audit.user_id is None
        assert audit.new_values["service_executor_id_hash"] == service_hash
        assert audit.new_values["human_user_impersonated"] is False
        assert audit.new_values["remote_content_read_performed"] is False
        assert audit.new_values["document_mutated"] is False
        assert audit.new_values["processing_enqueued"] is False
        assert audit.new_values["ai_executed"] is False

    assert adapter.calls == 1

    with TestingSessionLocal() as db:
        observation2, consumption2, outcome2 = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id=service_id,
            now=datetime(2026, 9, 20, 0, 5, tzinfo=UTC),
        )
        assert outcome2 == "replayed"
        assert observation2.id == observation.id
        assert consumption2.id == consumption.id
        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 1

    assert adapter.calls == 1


def test_phase_ae_links_existing_human_observation_without_second_provider_read(
    monkeypatch,
) -> None:
    (
        actor_id,
        profile_id,
        schedule_id,
        organization_id,
        _document_id,
        dispatch_id,
        adapter,
    ) = _prepare(monkeypatch, "human-race")

    with TestingSessionLocal() as db:
        human_observation, outcome = execute_due_tick_observation(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            schedule_id=schedule_id,
            executed_by_id=actor_id,
            request_key="phase-ae-human-wins",
            reason=(
                "Complete the exact due tick through the existing human AC path "
                "before the service executor consumes its immutable dispatch."
            ),
            now=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        )
        assert outcome == "completed"
        assert human_observation.actor_kind == "human"
        assert human_observation.executed_by_id == actor_id
        assert human_observation.service_executor_id_hash is None

    assert adapter.calls == 1

    with TestingSessionLocal() as db:
        observation, consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id="external-evidence-observer-v1",
            now=datetime(2026, 9, 20, 0, 1, tzinfo=UTC),
        )
        assert outcome == "linked_existing"
        assert observation.id == human_observation.id
        assert observation.actor_kind == "human"
        assert consumption.status == "linked_existing"
        assert consumption.observation_execution_id == human_observation.id
        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 1

    assert adapter.calls == 1


def test_phase_ae_worker_run_once_consumes_at_most_one_dispatch(monkeypatch) -> None:
    (
        _actor_id,
        _profile_id,
        _schedule_id,
        _organization_id,
        _document_id,
        _dispatch_id,
        adapter,
    ) = _prepare(monkeypatch, "worker")

    monkeypatch.setattr(
        observation_worker,
        "create_session",
        TestingSessionLocal,
    )

    assert observation_worker.run_once("external-evidence-observer-v1") is True
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceDueTickDispatch).count() == 1
        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 1

    assert observation_worker.run_once("external-evidence-observer-v1") is False
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 1

    assert adapter.calls == 1

from datetime import UTC, datetime
import hashlib
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.external_document_sources.due_tick_dispatch_models import (
    ExternalDocumentSourceDueTickDispatch,
    ExternalDocumentSourceDueTickDispatchReceipt,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    dispatch_next_due_tick,
    ensure_due_tick_dispatch_integrity,
)
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.due_tick_observation_service import (
    execute_due_tick_observation,
)
from app.modules.processing.models import DocumentProcessingJob
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_change_detection import _ChangeAdapter
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


def test_phase_ad_dispatches_one_due_tick_db_only_without_human_impersonation(monkeypatch) -> None:
    actor_id, profile_id, _claim_id, initial_execution, binding = _bound_v1(
        monkeypatch,
        "ad-db-only",
    )
    response = _authorize_schedule(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ad-schedule",
        cadence="hourly",
        effective_at="2026-09-20T00:00:00Z",
        headers=_mfa_headers(actor_id),
    )
    assert response.status_code == 201, response.text
    schedule_id = UUID(response.json()["id"])
    now = datetime(2026, 9, 20, 2, 0, tzinfo=UTC)

    document_id = UUID(initial_execution["document_id"])
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

        dispatch = dispatch_next_due_tick(
            db,
            worker_id="scheduler-node-a",
            now=now,
        )
        assert dispatch is not None
        assert dispatch.schedule_id == schedule_id
        assert dispatch.due_at == datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
        assert dispatch.status == "dispatched"
        assert dispatch.worker_id_hash == hashlib.sha256(b"scheduler-node-a").hexdigest()
        ensure_due_tick_dispatch_integrity(db, dispatch)

        assert db.query(ExternalDocumentSourceDueTickDispatch).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchReceipt).count() == 1
        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 0
        assert db.query(DocumentProcessingJob).count() == jobs_before

        unchanged_document = db.get(Document, document_id)
        assert unchanged_document is not None
        assert (
            unchanged_document.is_current,
            unchanged_document.version_number,
            unchanged_document.file_hash,
            unchanged_document.processing_status,
        ) == original_document

        audit = db.query(AuditLog).filter(
            AuditLog.action == "DISPATCH_EXTERNAL_EVIDENCE_DUE_TICK"
        ).one()
        assert audit.user_id is None
        assert audit.new_values["worker_id_hash"] == dispatch.worker_id_hash
        assert audit.new_values["remote_metadata_read_performed"] is False
        assert audit.new_values["document_mutated"] is False
        assert audit.new_values["processing_enqueued"] is False
        assert audit.new_values["ai_executed"] is False

    with TestingSessionLocal() as db:
        duplicate = dispatch_next_due_tick(
            db,
            worker_id="scheduler-node-b",
            now=now,
        )
        assert duplicate is None
        assert db.query(ExternalDocumentSourceDueTickDispatch).count() == 1


def test_phase_ad_skips_not_due_schedule(monkeypatch) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ad-not-due",
    )
    response = _authorize_schedule(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ad-future",
        cadence="daily",
        effective_at="2099-01-01T00:00:00Z",
        headers=_mfa_headers(actor_id),
    )
    assert response.status_code == 201, response.text

    with TestingSessionLocal() as db:
        dispatch = dispatch_next_due_tick(
            db,
            worker_id="scheduler-node-a",
            now=datetime(2026, 9, 20, 2, 0, tzinfo=UTC),
        )
        assert dispatch is None
        assert db.query(ExternalDocumentSourceDueTickDispatch).count() == 0
        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 0


def test_phase_ad_follows_completed_ac_tick_without_skipping_overdue_sequence(monkeypatch) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ad-after-ac",
    )
    response = _authorize_schedule(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ad-after-ac-schedule",
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
        first, outcome = execute_due_tick_observation(
            db,
            organization_id=UUID(binding["organization_id"]),
            profile_id=UUID(profile_id),
            schedule_id=schedule_id,
            executed_by_id=actor_id,
            request_key="phase-ad-after-ac-first",
            reason=(
                "Consume the first exact recurring tick before scheduler dispatch "
                "so AD must derive the next overdue tick without skipping."
            ),
            now=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        )
        assert outcome == "completed"
        assert first.due_at == datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
        assert adapter.calls == 1

    with TestingSessionLocal() as db:
        dispatch = dispatch_next_due_tick(
            db,
            worker_id="scheduler-node-after-ac",
            now=datetime(2026, 9, 20, 2, 30, tzinfo=UTC),
        )
        assert dispatch is not None
        assert dispatch.schedule_id == schedule_id
        assert dispatch.due_at == datetime(2026, 9, 20, 1, 0, tzinfo=UTC)
        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatch).count() == 1
        assert adapter.calls == 1

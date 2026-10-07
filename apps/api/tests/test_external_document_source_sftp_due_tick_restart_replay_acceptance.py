from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.modules.documents.models import Document
from app.modules.external_document_sources.due_tick_dispatch_consumption_models import (
    ExternalDocumentSourceDueTickDispatchConsumption,
    ExternalDocumentSourceDueTickDispatchConsumptionReceipt,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
    ExternalDocumentSourceDueTickObservationReceipt,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    clear_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.processing.models import DocumentProcessingJob
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_sftp_due_tick_service_executor import (
    _SERVICE_ID,
    _io_snapshot,
    _prepare,
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)


def setup_function() -> None:
    _phase_y_setup()


def teardown_function() -> None:
    _phase_y_teardown()


def test_ae_c_due_tick_replay_survives_provider_registry_restart_without_second_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, execution, _binding, dispatch_id = _prepare(
        monkeypatch,
        "ae-c-provider-restart",
    )
    document_id = UUID(execution["document_id"])
    before_consume = _io_snapshot(chain, adapter)

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        document_state = (
            document.is_current,
            document.version_number,
            document.file_hash,
            document.processing_status,
        )
        jobs_before = db.query(DocumentProcessingJob).count()

        observation, consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id=_SERVICE_ID,
            now=datetime(2026, 9, 28, 18, 0, tzinfo=UTC),
        )
        assert outcome == "consumed"
        assert observation.result_status == "unchanged"

        durable_counts = {
            "observations": db.query(
                ExternalDocumentSourceDueTickObservationExecution
            ).count(),
            "observation_receipts": db.query(
                ExternalDocumentSourceDueTickObservationReceipt
            ).count(),
            "consumptions": db.query(
                ExternalDocumentSourceDueTickDispatchConsumption
            ).count(),
            "consumption_receipts": db.query(
                ExternalDocumentSourceDueTickDispatchConsumptionReceipt
            ).count(),
            "processing_jobs": db.query(DocumentProcessingJob).count(),
        }
        assert durable_counts == {
            "observations": 1,
            "observation_receipts": 1,
            "consumptions": 1,
            "consumption_receipts": 1,
            "processing_jobs": jobs_before,
        }
        observation_id = observation.id
        consumption_id = consumption.id

    after_first_consume = _io_snapshot(chain, adapter)
    assert (
        after_first_consume["provider_stat_calls"]
        == before_consume["provider_stat_calls"] + 1
    )
    assert (
        after_first_consume["remote_content_reads"]
        == before_consume["remote_content_reads"]
    )

    # Simulate a service/process restart with an empty provider metadata registry.
    # Exact replay must resolve from the committed immutable consumption instead
    # of touching the provider again.
    clear_external_document_source_sftp_exact_file_metadata_adapter()

    with TestingSessionLocal() as db:
        replay_observation, replay_consumption, replay_outcome = (
            consume_due_tick_dispatch(
                db,
                dispatch_id=dispatch_id,
                service_executor_id=_SERVICE_ID,
                now=datetime(2026, 9, 28, 18, 5, tzinfo=UTC),
            )
        )
        assert replay_outcome == "replayed"
        assert replay_observation.id == observation_id
        assert replay_consumption.id == consumption_id

        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 1
        assert db.query(ExternalDocumentSourceDueTickObservationReceipt).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 1
        assert (
            db.query(ExternalDocumentSourceDueTickDispatchConsumptionReceipt).count()
            == 1
        )
        assert db.query(DocumentProcessingJob).count() == jobs_before

        document = db.get(Document, document_id)
        assert document is not None
        assert (
            document.is_current,
            document.version_number,
            document.file_hash,
            document.processing_status,
        ) == document_state

    assert _io_snapshot(chain, adapter) == after_first_consume

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.external_document_sources.due_tick_dispatch_consumption_models import (
    ExternalDocumentSourceDueTickDispatchConsumption,
    ExternalDocumentSourceDueTickDispatchConsumptionReceipt,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
    ensure_due_tick_dispatch_consumption_integrity,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    dispatch_next_due_tick,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
    ExternalDocumentSourceDueTickObservationReceipt,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.processing.models import DocumentProcessingJob
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_recurring_observation_schedule import (
    _authorize as _authorize_schedule,
    _mfa_headers,
)
from tests.test_external_document_source_sftp_recurring_observation_schedule import (
    setup_function as _x_setup,
    teardown_function as _x_teardown,
)
from tests.test_external_document_source_sftp_recurring_provider_lineage import (
    _bound_sftp,
)


_NOW = datetime(2026, 9, 28, 18, 0, tzinfo=UTC)
_SERVICE_ID = "external-evidence-observer-v1"


def setup_function() -> None:
    _x_setup()


def teardown_function() -> None:
    _x_teardown()


def _io_snapshot(chain: dict, adapter) -> dict:
    return {
        "provider_stat_calls": len(adapter.calls),
        "staged_put_calls": chain["p_store"].put_calls,
        "staged_head_calls": chain["p_store"].head_calls,
        "staged_get_calls": chain["p_store"].get_calls,
        "remote_content_reads": len(chain["p_read_adapter"].calls),
    }


def _prepare(monkeypatch: pytest.MonkeyPatch, suffix: str):
    chain, adapter, _claim_id, _authorization, execution, binding = _bound_sftp(
        monkeypatch,
        f"sftp-phase-y-{suffix}",
    )
    schedule = _authorize_schedule(
        chain["profile_id"],
        binding["id"],
        chain["requester_id"],
        key=f"sftp-phase-y-{suffix}-schedule",
        cadence="hourly",
        effective_at="2026-09-28T18:00:00Z",
        headers=_mfa_headers(chain["requester_id"]),
    )
    assert schedule.status_code == 201, schedule.text

    before_dispatch = _io_snapshot(chain, adapter)
    with TestingSessionLocal() as db:
        dispatch = dispatch_next_due_tick(
            db,
            worker_id=f"sftp-phase-y-{suffix}-scheduler",
            now=_NOW,
        )
        assert dispatch is not None
        assert dispatch.provider_kind == "sftp"
        assert dispatch.binding_id == UUID(binding["id"])
        assert dispatch.current_document_id == UUID(execution["document_id"])
        dispatch_id = dispatch.id

    assert _io_snapshot(chain, adapter) == before_dispatch
    return chain, adapter, execution, binding, dispatch_id


def test_phase_y_generic_dispatch_and_service_consume_sftp_once_with_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, execution, binding, dispatch_id = _prepare(
        monkeypatch,
        "unchanged",
    )
    document_id = UUID(execution["document_id"])
    before_consume = _io_snapshot(chain, adapter)
    service_hash = hashlib.sha256(_SERVICE_ID.encode("utf-8")).hexdigest()

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
            service_executor_id=_SERVICE_ID,
            now=_NOW,
        )
        assert outcome == "consumed"
        assert observation.provider_kind == "sftp"
        assert observation.result_status == "unchanged"
        assert observation.actor_kind == "service"
        assert observation.executed_by_id is None
        assert observation.service_executor_id_hash == service_hash
        assert observation.provider_lineage_observation_id is None
        assert observation.provider_lineage_checkpoint_id is None
        assert observation.sftp_provider_lineage_observation_id is not None
        assert observation.sftp_provider_lineage_checkpoint_id is not None
        assert observation.binding_id == UUID(binding["id"])
        assert observation.current_document_id == document_id

        assert consumption.status == "executed"
        assert consumption.service_executor_id_hash == service_hash
        assert consumption.observation_execution_id == observation.id
        ensure_due_tick_dispatch_consumption_integrity(db, consumption)

        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 1
        assert db.query(ExternalDocumentSourceDueTickObservationReceipt).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 1
        assert (
            db.query(ExternalDocumentSourceDueTickDispatchConsumptionReceipt).count()
            == 1
        )
        assert db.query(DocumentProcessingJob).count() == jobs_before

        unchanged = db.get(Document, document_id)
        assert unchanged is not None
        assert (
            unchanged.is_current,
            unchanged.version_number,
            unchanged.file_hash,
            unchanged.processing_status,
        ) == original_document

        audit_rows = (
            db.query(AuditLog)
            .filter(
                AuditLog.action
                == "CONSUME_EXTERNAL_EVIDENCE_DUE_TICK_DISPATCH"
            )
            .all()
        )
        assert len(audit_rows) == 1
        assert audit_rows[0].new_values["service_executor_id_hash"] == service_hash
        assert audit_rows[0].new_values["human_user_impersonated"] is False
        assert audit_rows[0].new_values["remote_content_read_performed"] is False
        assert audit_rows[0].new_values["document_mutated"] is False
        assert audit_rows[0].new_values["processing_enqueued"] is False
        assert audit_rows[0].new_values["ai_executed"] is False

    after_consume = _io_snapshot(chain, adapter)
    assert (
        after_consume["provider_stat_calls"]
        == before_consume["provider_stat_calls"] + 1
    )
    for key in (
        "staged_put_calls",
        "staged_head_calls",
        "staged_get_calls",
        "remote_content_reads",
    ):
        assert after_consume[key] == before_consume[key]

    with TestingSessionLocal() as db:
        observation2, consumption2, outcome2 = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id=_SERVICE_ID,
            now=datetime(2026, 9, 28, 18, 5, tzinfo=UTC),
        )
        assert outcome2 == "replayed"
        assert observation2.id == observation.id
        assert consumption2.id == consumption.id

    assert _io_snapshot(chain, adapter) == after_consume


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    (("changed", "changed"), ("missing", "missing")),
)
def test_phase_y_sftp_service_consume_normalizes_changed_and_missing(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_status: str,
) -> None:
    chain, adapter, _execution, _binding, dispatch_id = _prepare(
        monkeypatch,
        f"{mode}-result",
    )
    adapter.mode = mode
    before = _io_snapshot(chain, adapter)

    with TestingSessionLocal() as db:
        observation, consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id=_SERVICE_ID,
            now=_NOW,
        )
        assert outcome == "consumed"
        assert observation.provider_kind == "sftp"
        assert observation.result_status == expected_status
        assert consumption.status == "executed"

        if expected_status == "missing":
            assert observation.observed_projection_hash is None
            assert observation.observed_byte_size is None
            assert observation.observed_modified_at is None
        else:
            assert observation.observed_projection_hash is not None
            assert (
                observation.observed_projection_hash
                != observation.baseline_projection_hash
            )

    after = _io_snapshot(chain, adapter)
    assert after["provider_stat_calls"] == before["provider_stat_calls"] + 1
    assert after["remote_content_reads"] == before["remote_content_reads"]
    assert after["staged_put_calls"] == before["staged_put_calls"]
    assert after["staged_head_calls"] == before["staged_head_calls"]
    assert after["staged_get_calls"] == before["staged_get_calls"]


def test_phase_y_wrong_service_identity_fails_before_sftp_stat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _execution, _binding, dispatch_id = _prepare(
        monkeypatch,
        "wrong-service",
    )
    before = _io_snapshot(chain, adapter)

    with TestingSessionLocal() as db:
        with pytest.raises(ExternalDocumentSourceConflictError):
            consume_due_tick_dispatch(
                db,
                dispatch_id=dispatch_id,
                service_executor_id="different-internal-observer",
                now=_NOW,
            )
        db.rollback()

    assert _io_snapshot(chain, adapter) == before
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 0
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 0

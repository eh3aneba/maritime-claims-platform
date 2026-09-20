from datetime import UTC, datetime
import hashlib

import pytest

from app.modules.audit.models import AuditLog
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.observation_review_handoff_models import (
    ExternalDocumentSourceObservationReviewHandoff,
    ExternalDocumentSourceObservationReviewHandoffReceipt,
)
from app.modules.external_document_sources.observation_review_handoff_service import (
    ensure_observation_review_handoff_integrity,
    project_observation_review_handoff,
)
from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError
from app.workers import external_evidence_review_projector_worker as projector_worker
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_external_document_source_due_tick_service_executor import _prepare
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_generation_3_change_detection import (
    _baseline_projection,
)


def setup_function() -> None:
    _phase_y_setup()
    reset_database()


def teardown_function() -> None:
    _phase_y_teardown()


def _changed_result() -> ExactItemMetadataResult:
    baseline = _baseline_projection()
    changed = baseline.__class__(
        provider_item_id=baseline.provider_item_id,
        parent_item_id=baseline.parent_item_id,
        item_kind=baseline.item_kind,
        display_name=baseline.display_name,
        mime_type_class=baseline.mime_type_class,
        byte_size=(baseline.byte_size or 0) + 23,
        modified_at=datetime(2026, 9, 20, 1, 0, tzinfo=UTC),
        version_token_hash="e" * 64,
    )
    return ExactItemMetadataResult(found=True, item=changed)


def _consume_service_observation(monkeypatch, suffix: str, result: ExactItemMetadataResult):
    (
        _actor_id,
        _profile_id,
        _schedule_id,
        _organization_id,
        _document_id,
        dispatch_id,
        adapter,
    ) = _prepare(monkeypatch, suffix)
    adapter.result = result
    with TestingSessionLocal() as db:
        observation, _consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id="external-evidence-observer-v1",
            now=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        )
        assert outcome == "consumed"
        observation_id = observation.id
        result_status = observation.result_status
    return observation_id, result_status, adapter


def test_phase_af_projects_changed_observation_once_without_external_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation_id, result_status, adapter = _consume_service_observation(
        monkeypatch,
        "af-changed",
        _changed_result(),
    )
    assert result_status == "changed"
    assert adapter.calls == 1

    projector_id = "external-evidence-review-projector-v1"
    projector_hash = hashlib.sha256(projector_id.encode("utf-8")).hexdigest()

    with TestingSessionLocal() as db:
        handoff, outcome = project_observation_review_handoff(
            db,
            observation_execution_id=observation_id,
            projector_id=projector_id,
            now=datetime(2026, 9, 20, 0, 1, tzinfo=UTC),
        )
        assert handoff is not None
        assert outcome == "projected"
        assert handoff.status == "pending"
        assert handoff.result_status == "changed"
        assert handoff.observation_execution_id == observation_id
        assert handoff.projector_id_hash == projector_hash
        ensure_observation_review_handoff_integrity(db, handoff)

        receipt = db.query(ExternalDocumentSourceObservationReviewHandoffReceipt).one()
        assert receipt.handoff_id == handoff.id
        assert receipt.event_type == "projected"
        assert receipt.status_after == "pending"
        assert receipt.projector_id_hash == projector_hash

        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.action
                == "PROJECT_EXTERNAL_EVIDENCE_OBSERVATION_REVIEW_HANDOFF"
            )
            .one()
        )
        assert audit.user_id is None
        assert audit.new_values["provider_client_constructed"] is False
        assert audit.new_values["remote_metadata_read_performed"] is False
        assert audit.new_values["remote_content_read_performed"] is False
        assert audit.new_values["document_mutated"] is False
        assert audit.new_values["evidence_admitted"] is False
        assert audit.new_values["processing_enqueued"] is False
        assert audit.new_values["ai_executed"] is False
        handoff_id = handoff.id

    assert adapter.calls == 1

    with TestingSessionLocal() as db:
        replay, outcome = project_observation_review_handoff(
            db,
            observation_execution_id=observation_id,
            projector_id=projector_id,
        )
        assert replay is not None
        assert replay.id == handoff_id
        assert outcome == "replayed"
        assert db.query(ExternalDocumentSourceObservationReviewHandoff).count() == 1
        assert db.query(ExternalDocumentSourceObservationReviewHandoffReceipt).count() == 1

    assert adapter.calls == 1


def test_phase_af_projects_missing_but_ignores_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_id, missing_status, missing_adapter = _consume_service_observation(
        monkeypatch,
        "af-missing",
        ExactItemMetadataResult(
            found=False,
            item=None,
            failure_code="not_found",
        ),
    )
    assert missing_status == "missing"

    with TestingSessionLocal() as db:
        handoff, outcome = project_observation_review_handoff(
            db,
            observation_execution_id=missing_id,
            projector_id="external-evidence-review-projector-v1",
        )
        assert handoff is not None
        assert outcome == "projected"
        assert handoff.result_status == "missing"
        assert handoff.observed_projection_hash is None
    assert missing_adapter.calls == 1

    unchanged_id, unchanged_status, unchanged_adapter = _consume_service_observation(
        monkeypatch,
        "af-unchanged",
        ExactItemMetadataResult(
            found=True,
            item=_baseline_projection(),
        ),
    )
    assert unchanged_status == "unchanged"

    with TestingSessionLocal() as db:
        handoff, outcome = project_observation_review_handoff(
            db,
            observation_execution_id=unchanged_id,
            projector_id="external-evidence-review-projector-v1",
        )
        assert handoff is None
        assert outcome == "ineligible"
        rows = db.query(ExternalDocumentSourceObservationReviewHandoff).all()
        assert len(rows) == 1
        assert rows[0].observation_execution_id == missing_id
    assert unchanged_adapter.calls == 1


def test_phase_af_worker_run_once_projects_at_most_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation_id, _status, adapter = _consume_service_observation(
        monkeypatch,
        "af-worker",
        _changed_result(),
    )
    monkeypatch.setattr(projector_worker, "create_session", TestingSessionLocal)

    assert projector_worker.run_once("external-evidence-review-projector-v1") is True
    with TestingSessionLocal() as db:
        row = db.query(ExternalDocumentSourceObservationReviewHandoff).one()
        assert row.observation_execution_id == observation_id

    assert projector_worker.run_once("external-evidence-review-projector-v1") is False
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationReviewHandoff).count() == 1
    assert adapter.calls == 1


def test_phase_af_unconfigured_projector_fails_before_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation_id, _status, adapter = _consume_service_observation(
        monkeypatch,
        "af-projector-auth",
        _changed_result(),
    )
    with TestingSessionLocal() as db:
        with pytest.raises(ExternalDocumentSourceConflictError):
            project_observation_review_handoff(
                db,
                observation_execution_id=observation_id,
                projector_id="different-review-projector",
            )
        db.rollback()
        assert db.query(ExternalDocumentSourceObservationReviewHandoff).count() == 0
    assert adapter.calls == 1

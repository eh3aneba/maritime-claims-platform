from __future__ import annotations

from datetime import UTC, datetime
import hashlib

import pytest

from app.modules.audit.models import AuditLog
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
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_sftp_due_tick_service_executor import (
    _SERVICE_ID,
    _io_snapshot,
    _prepare,
    setup_function as _y_setup,
    teardown_function as _y_teardown,
)


_PROJECTOR_ID = "external-evidence-review-projector-v1"
_NOW = datetime(2026, 9, 28, 18, 0, tzinfo=UTC)


def setup_function() -> None:
    _y_setup()


def teardown_function() -> None:
    _y_teardown()


def _observation(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    *,
    mode: str,
):
    chain, adapter, _execution, _binding, dispatch_id = _prepare(
        monkeypatch,
        suffix,
    )
    adapter.mode = mode
    with TestingSessionLocal() as db:
        observation, _consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id=_SERVICE_ID,
            now=_NOW,
        )
        assert outcome == "consumed"
        observation_id = observation.id
        result_status = observation.result_status
    return chain, adapter, observation_id, result_status


@pytest.mark.parametrize("mode", ["changed", "missing"])
def test_phase_z_projects_sftp_changed_or_missing_to_pending_review_without_io(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    chain, adapter, observation_id, result_status = _observation(
        monkeypatch,
        f"sftp-phase-z-{mode}",
        mode=mode,
    )
    assert result_status == mode
    before_projection = _io_snapshot(chain, adapter)
    projector_hash = hashlib.sha256(_PROJECTOR_ID.encode("utf-8")).hexdigest()

    with TestingSessionLocal() as db:
        handoff, outcome = project_observation_review_handoff(
            db,
            observation_execution_id=observation_id,
            projector_id=_PROJECTOR_ID,
            now=datetime(2026, 9, 28, 18, 1, tzinfo=UTC),
        )
        assert handoff is not None
        assert outcome == "projected"
        assert handoff.provider_kind == "sftp"
        assert handoff.status == "pending"
        assert handoff.result_status == mode
        assert handoff.observation_execution_id == observation_id
        assert handoff.projector_id_hash == projector_hash
        if mode == "missing":
            assert handoff.observed_projection_hash is None
        else:
            assert handoff.observed_projection_hash is not None

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

    assert _io_snapshot(chain, adapter) == before_projection

    with TestingSessionLocal() as db:
        replay, outcome = project_observation_review_handoff(
            db,
            observation_execution_id=observation_id,
            projector_id=_PROJECTOR_ID,
        )
        assert replay is not None
        assert replay.id == handoff_id
        assert outcome == "replayed"
        assert db.query(ExternalDocumentSourceObservationReviewHandoff).count() == 1
        assert (
            db.query(ExternalDocumentSourceObservationReviewHandoffReceipt).count()
            == 1
        )

    assert _io_snapshot(chain, adapter) == before_projection


def test_phase_z_sftp_unchanged_observation_is_not_review_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, observation_id, result_status = _observation(
        monkeypatch,
        "sftp-phase-z-unchanged",
        mode="unchanged",
    )
    assert result_status == "unchanged"
    before_projection = _io_snapshot(chain, adapter)

    with TestingSessionLocal() as db:
        handoff, outcome = project_observation_review_handoff(
            db,
            observation_execution_id=observation_id,
            projector_id=_PROJECTOR_ID,
        )
        assert handoff is None
        assert outcome == "ineligible"
        assert db.query(ExternalDocumentSourceObservationReviewHandoff).count() == 0

    assert _io_snapshot(chain, adapter) == before_projection

from uuid import UUID

import pytest

from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.checkpoint_generation_3_models import (
    ExternalDocumentSourceCheckpointGeneration3Execution,
)
from app.modules.external_document_sources.generation_3_change_detection_models import (
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
    ExternalDocumentSourceGeneration3ChangeDetectionReceipt,
)
from app.modules.external_document_sources.successor_change_detection_models import (
    ExternalDocumentSourceSuccessorChangeDetectionExecution,
)
from app.modules.external_document_sources.successor_versioned_restaging_models import (
    ExternalDocumentSourceSuccessorVersionedRestagingExecution,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import _ChangeAdapter
from tests.test_external_document_source_discovery import _headers
from tests.test_external_document_source_generation_3_change_detection import (
    _baseline_projection,
    _completed_phase_u,
    _observe,
    setup_function as _phase_v_setup,
    teardown_function as _phase_v_teardown,
)


def setup_function() -> None:
    _phase_v_setup()


def teardown_function() -> None:
    _phase_v_teardown()


@pytest.mark.parametrize("target", ["u", "t", "s"])
def test_phase_v_upstream_tamper_fails_closed_before_provider_call(target: str) -> None:
    (
        requester_id,
        profile_id,
        _binding_id,
        _checkpoint,
        _change,
        _q_body,
        _r_body,
        s_body,
        t_body,
        u_body,
        _metadata_adapter,
        _q_adapter,
        _phase_m_read_adapter,
        _t_adapter,
        _store,
    ) = _completed_phase_u()

    with TestingSessionLocal() as db:
        if target == "u":
            row = db.get(ExternalDocumentSourceCheckpointGeneration3Execution, UUID(u_body["id"]))
            assert row is not None
            row.successor_checkpoint_state_hash = "a" * 64
        elif target == "t":
            row = db.get(ExternalDocumentSourceSuccessorVersionedRestagingExecution, UUID(t_body["id"]))
            assert row is not None
            row.content_proof_hash = "b" * 64
        else:
            row = db.get(ExternalDocumentSourceSuccessorChangeDetectionExecution, UUID(s_body["id"]))
            assert row is not None
            row.completion_hash = "c" * 64
        db.commit()

    adapter = _ChangeAdapter()
    adapter.result = ExactItemMetadataResult(found=True, item=_baseline_projection())
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", adapter,
    )
    response = _observe(
        profile_id,
        u_body["id"],
        requester_id,
        key=f"phase-v-upstream-tamper-{target}",
    )
    assert response.status_code == 409, response.text
    assert adapter.calls == 0
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceGeneration3ChangeDetectionExecution).count() == 0


def test_phase_v_receipt_tamper_fails_closed_without_second_provider_call() -> None:
    (
        requester_id,
        profile_id,
        _binding_id,
        _checkpoint,
        _change,
        _q_body,
        _r_body,
        _s_body,
        _t_body,
        u_body,
        _metadata_adapter,
        _q_adapter,
        _phase_m_read_adapter,
        _t_adapter,
        _store,
    ) = _completed_phase_u()
    adapter = _ChangeAdapter()
    adapter.result = ExactItemMetadataResult(found=True, item=_baseline_projection())
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", adapter,
    )
    response = _observe(profile_id, u_body["id"], requester_id, key="phase-v-receipt-tamper")
    assert response.status_code == 201, response.text
    execution_id = response.json()["id"]
    assert adapter.calls == 1

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceGeneration3ChangeDetectionReceipt)
            .filter(ExternalDocumentSourceGeneration3ChangeDetectionReceipt.execution_id == UUID(execution_id))
            .order_by(ExternalDocumentSourceGeneration3ChangeDetectionReceipt.sequence_number.asc())
            .first()
        )
        assert receipt is not None
        receipt.decision_hash = "d" * 64
        db.commit()

    fetched = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/generation-3-successor-change-detection-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fetched.status_code == 409, fetched.text
    assert adapter.calls == 1

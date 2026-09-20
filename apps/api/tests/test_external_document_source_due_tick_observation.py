from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
    ExternalDocumentSourceDueTickObservationReceipt,
)
from app.modules.processing.models import DocumentProcessingJob
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import _ChangeAdapter
from tests.test_external_document_source_family_version_admission import (
    _V2_BODY,
    _V2_MODIFIED,
    _V2_VERSION,
    _aa_admit,
    _authorize_aa,
    _bound_v1,
    _enable_clean_aa,
    _later_candidate,
)
from tests.test_external_document_source_generation_3_change_detection import (
    _baseline_projection,
)
from tests.test_external_document_source_recurring_observation_schedule import (
    _authorize as _authorize_schedule,
    _disable as _disable_schedule,
    _mfa_headers,
)

_REASON = (
    "Consume exactly one due recurring observation tick using metadata only "
    "without staging content or mutating canonical Evidence."
)


def _execute(
    profile_id: str,
    schedule_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _REASON,
    headers: dict[str, str] | None = None,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/recurring-observation-schedules/{schedule_id}/execute-due"
        ),
        headers=headers or _mfa_headers(actor_id),
        json=payload,
    )


def test_phase_ac_consumes_one_overdue_tick_at_a_time_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, initial_execution, binding = _bound_v1(
        monkeypatch,
        "ac-lifecycle",
    )
    headers = _mfa_headers(actor_id)
    schedule = _authorize_schedule(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ac-schedule",
        cadence="hourly",
        effective_at="2026-09-20T00:00:00Z",
        headers=headers,
    )
    assert schedule.status_code == 201, schedule.text
    schedule_body = schedule.json()

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

    document_id = UUID(initial_execution["document_id"])
    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        original = (
            document.is_current,
            document.version_number,
            document.file_hash,
            document.processing_status,
        )
        jobs_before = db.query(DocumentProcessingJob).count()

    forbidden = _execute(
        profile_id,
        schedule_body["id"],
        actor_id,
        key="phase-ac-forbidden",
        headers=headers,
        extra={
            "due_at": "2026-09-19T00:00:00Z",
            "provider_item_id": "caller-item",
            "remote_path": "/caller/path",
            "content": "caller-content",
            "ai_authorized": True,
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert adapter.calls == 0

    first = _execute(
        profile_id,
        schedule_body["id"],
        actor_id,
        key="phase-ac-tick-1",
        headers=headers,
    )
    assert first.status_code == 201, first.text
    body1 = first.json()
    assert body1["status"] == "completed"
    assert body1["result_status"] == "unchanged"
    assert body1["due_at"] == "2026-09-20T00:00:00+00:00"
    assert body1["current_version_number"] == 1
    assert body1["baseline_projection_hash"] == binding["source_projection_hash"]
    assert body1["observed_projection_hash"] == body1["baseline_projection_hash"]
    assert adapter.calls == 1

    for field in (
        "schedule_authority_verified",
        "family_binding_verified",
        "current_document_verified",
        "provider_lineage_verified",
        "due_tick_verified",
        "provider_client_constructed",
        "exact_item_metadata_read_performed",
    ):
        assert body1[field] is True
    for field in (
        "remote_list_performed",
        "remote_content_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "document_mutated",
        "evidence_admitted",
        "processing_enqueued",
        "ai_executed",
        "claim_mutated",
        "checkpoint_advanced",
        "background_worker_started",
    ):
        assert body1[field] is False

    replay = _execute(
        profile_id,
        schedule_body["id"],
        actor_id,
        key="phase-ac-tick-1",
        headers=headers,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == body1["id"]
    assert adapter.calls == 1

    altered = _execute(
        profile_id,
        schedule_body["id"],
        actor_id,
        key="phase-ac-tick-1",
        reason=(
            "Alter the replay reason so the same key cannot silently authorize "
            "a different recurring observation execution."
        ),
        headers=headers,
    )
    assert altered.status_code == 409, altered.text
    assert adapter.calls == 1

    changed_projection = _baseline_projection()
    changed_projection = changed_projection.__class__(
        provider_item_id=changed_projection.provider_item_id,
        parent_item_id=changed_projection.parent_item_id,
        item_kind=changed_projection.item_kind,
        display_name=changed_projection.display_name,
        mime_type_class=changed_projection.mime_type_class,
        byte_size=(changed_projection.byte_size or 0) + 17,
        modified_at=datetime(2026, 9, 20, 1, 0, tzinfo=UTC),
        version_token_hash="f" * 64,
    )
    adapter.result = ExactItemMetadataResult(
        found=True,
        item=changed_projection,
    )
    second = _execute(
        profile_id,
        schedule_body["id"],
        actor_id,
        key="phase-ac-tick-2",
        headers=headers,
    )
    assert second.status_code == 201, second.text
    body2 = second.json()
    assert body2["due_at"] == "2026-09-20T01:00:00+00:00"
    assert body2["result_status"] == "changed"
    assert body2["observed_projection_hash"] != body2["baseline_projection_hash"]
    assert adapter.calls == 2

    adapter.result = ExactItemMetadataResult(
        found=False,
        item=None,
        failure_code="not_found",
    )
    third = _execute(
        profile_id,
        schedule_body["id"],
        actor_id,
        key="phase-ac-tick-3",
        headers=headers,
    )
    assert third.status_code == 201, third.text
    body3 = third.json()
    assert body3["due_at"] == "2026-09-20T02:00:00+00:00"
    assert body3["result_status"] == "missing"
    assert body3["observed_projection_hash"] is None
    assert body3["observed_display_name_hash"] is None
    assert adapter.calls == 3

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        assert (
            document.is_current,
            document.version_number,
            document.file_hash,
            document.processing_status,
        ) == original
        assert db.query(DocumentProcessingJob).count() == jobs_before
        rows = (
            db.query(ExternalDocumentSourceDueTickObservationExecution)
            .order_by(ExternalDocumentSourceDueTickObservationExecution.due_at.asc())
            .all()
        )
        assert [row.result_status for row in rows] == [
            "unchanged",
            "changed",
            "missing",
        ]
        assert db.query(ExternalDocumentSourceDueTickObservationReceipt).count() == 3

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/due-tick-observations/{body1['id']}/receipts"
        ),
        headers=headers,
    )
    assert receipts.status_code == 200, receipts.text
    assert len(receipts.json()) == 1
    assert receipts.json()[0]["event_type"] == "completed"


def test_phase_ac_not_due_and_disabled_schedule_fail_before_provider_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ac-gates",
    )
    headers = _mfa_headers(actor_id)
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

    future = _authorize_schedule(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ac-future-schedule",
        cadence="daily",
        effective_at="2099-01-01T00:00:00Z",
        headers=headers,
    )
    assert future.status_code == 201, future.text

    not_due = _execute(
        profile_id,
        future.json()["id"],
        actor_id,
        key="phase-ac-not-due",
        headers=headers,
    )
    assert not_due.status_code == 409, not_due.text
    assert adapter.calls == 0

    stopped = _disable_schedule(
        profile_id,
        future.json()["id"],
        actor_id,
        key="phase-ac-disable-future",
        headers=headers,
    )
    assert stopped.status_code == 200, stopped.text

    disabled = _execute(
        profile_id,
        future.json()["id"],
        actor_id,
        key="phase-ac-disabled",
        headers=headers,
    )
    assert disabled.status_code == 409, disabled.text
    assert adapter.calls == 0


def test_phase_ac_uses_current_aa_version_as_observation_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ac-v2",
    )
    candidate, metadata_adapter, projection = _later_candidate(
        profile_id=profile_id,
        actor_id=actor_id,
        suffix="ac-v2",
        body=_V2_BODY,
        version=_V2_VERSION,
        modified=_V2_MODIFIED,
    )
    authorization = _authorize_aa(
        profile_id,
        binding["id"],
        candidate["id"],
        actor_id,
        key="phase-ac-v2-auth",
    )
    assert authorization.status_code == 201, authorization.text
    _enable_clean_aa(monkeypatch)
    admitted = _aa_admit(
        profile_id,
        binding["id"],
        authorization.json()["id"],
        actor_id,
        key="phase-ac-v2-admit",
    )
    assert admitted.status_code == 201, admitted.text
    v2 = admitted.json()
    assert v2["new_version_number"] == 2

    headers = _mfa_headers(actor_id)
    schedule = _authorize_schedule(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ac-v2-schedule",
        cadence="hourly",
        effective_at="2026-09-20T00:00:00Z",
        headers=headers,
    )
    assert schedule.status_code == 201, schedule.text

    metadata_adapter.result = ExactItemMetadataResult(
        found=True,
        item=projection,
    )
    calls_before = metadata_adapter.calls
    observed = _execute(
        profile_id,
        schedule.json()["id"],
        actor_id,
        key="phase-ac-v2-tick",
        headers=headers,
    )
    assert observed.status_code == 201, observed.text
    body = observed.json()
    assert body["current_document_id"] == v2["new_document_id"]
    assert body["current_version_number"] == 2
    assert body["baseline_projection_hash"] == v2["fresh_projection_hash"]
    assert body["baseline_version_token_hash"] == _V2_VERSION
    assert body["result_status"] == "unchanged"
    assert metadata_adapter.calls == calls_before + 1

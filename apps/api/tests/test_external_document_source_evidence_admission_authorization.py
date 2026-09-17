import json
from dataclasses import replace
from datetime import date, datetime, timezone
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.evidence_admission_authorization_models import (
    ExternalDocumentSourceEvidenceAdmissionAuthorization,
    ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt,
)
from app.modules.users.models import User
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import (
    _ChangeAdapter,
    _PROVIDER_URL,
    _RAW_RESPONSE,
    _SECRET,
    _TOKEN,
)
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_generation_3_change_detection import (
    _baseline_projection,
    _completed_phase_u,
    _observe,
    _upstream_io,
    setup_function as _phase_v_setup,
    teardown_function as _phase_v_teardown,
)

_AUTH_REASON = "Authorize this exact current governed external file version for later admission to this Claim."


def setup_function() -> None:
    _phase_v_setup()


def teardown_function() -> None:
    _phase_v_teardown()


def _seed_claim(actor_id: UUID, suffix: str = "w") -> UUID:
    with TestingSessionLocal() as db:
        actor = db.get(User, actor_id)
        assert actor is not None
        vessel = Vessel(
            organization_id=actor.organization_id,
            name=f"Phase W Vessel {suffix}",
            imo_number=None,
        )
        db.add(vessel)
        db.flush()
        claim = Claim(
            organization_id=actor.organization_id,
            vessel_id=vessel.id,
            claim_reference=f"H&M-W-{suffix}",
            incident_date=date(2026, 9, 1),
            notification_date=date(2026, 9, 2),
            incident_description="Phase W evidence authorization acceptance fixture.",
        )
        db.add(claim)
        db.commit()
        return claim.id


def _authorize(profile_id: str, observation_id: str, claim_id: UUID, actor_id: UUID, *, key: str, reason: str = _AUTH_REASON, extra: dict | None = None):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/generation-3-successor-change-detection-executions/{observation_id}/claims/{claim_id}/evidence-admission-authorizations",
        headers=_headers(actor_id),
        json=payload,
    )


def _unchanged_phase_v():
    upstream = _completed_phase_u()
    requester_id = upstream[0]
    profile_id = upstream[1]
    u_body = upstream[9]
    adapter = _ChangeAdapter()
    adapter.result = ExactItemMetadataResult(found=True, item=_baseline_projection())
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", adapter,
    )
    response = _observe(profile_id, u_body["id"], requester_id, key="phase-w-v-unchanged")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "unchanged"
    return upstream, adapter, response.json()


def test_phase_w_authorizes_exact_current_observation_without_admission_or_io() -> None:
    upstream, v_adapter, v_body = _unchanged_phase_v()
    requester_id = upstream[0]
    profile_id = upstream[1]
    metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store = upstream[10:15]
    claim_id = _seed_claim(requester_id, "success")

    with TestingSessionLocal() as db:
        documents_before = db.query(Document).count()
        claims_before = db.query(Claim).count()
        claim_before = db.get(Claim, claim_id)
        assert claim_before is not None
        status_before = claim_before.status
    io_before = (
        v_adapter.calls,
        _upstream_io(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store),
    )

    forbidden = _authorize(
        profile_id,
        v_body["id"],
        claim_id,
        requester_id,
        key="phase-w-forbidden",
        extra={
            "provider_item_id": "caller-controlled",
            "storage_key": "caller/storage/key",
            "url": _PROVIDER_URL,
            "content": "caller-content",
            "access_token": "caller-token",
        },
    )
    assert forbidden.status_code == 422, forbidden.text

    response = _authorize(
        profile_id,
        v_body["id"],
        claim_id,
        requester_id,
        key="phase-w-authorize-current",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    authorization_id = body["id"]
    assert body["status"] == "authorized"
    assert body["claim_id"] == str(claim_id)
    assert body["generation_3_change_detection_execution_id"] == v_body["id"]
    assert body["checkpoint_generation_3_execution_id"] == v_body["checkpoint_generation_3_execution_id"]
    assert body["authorized_projection_hash"] == v_body["observed_projection_hash"]
    assert body["authorized_display_name_hash"] == v_body["observed_display_name_hash"]
    assert body["authorized_version_token_hash"] == v_body["observed_version_token_hash"]
    assert body["candidate_content_proof_hash"] == v_body["candidate_content_proof_hash"]
    assert body["observation_completion_hash"] == v_body["completion_hash"]
    for field in (
        "upstream_checkpoint_generation_3_advance_completed",
        "upstream_generation_3_change_detection_completed",
        "latest_generation_3_observation_confirmed",
        "remote_version_current_at_authorization",
        "human_authorization_recorded",
    ):
        assert body[field] is True
    for field in (
        "provider_client_constructed",
        "remote_list_performed",
        "remote_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "document_created",
        "evidence_admitted",
        "content_parsed",
        "content_extracted",
        "claim_mutated",
        "admission_execution_performed",
        "background_sync_started",
    ):
        assert body[field] is False

    io_after = (
        v_adapter.calls,
        _upstream_io(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store),
    )
    assert io_after == io_before

    forbidden_fields = (
        "provider_item_id",
        "metadata_endpoint_url",
        "provider_origin",
        "storage_object_key",
        "storage_key",
        "content",
        "access_token",
        "client_secret",
    )
    serialized = json.dumps(body, sort_keys=True)
    for field in forbidden_fields:
        assert field not in body
    for marker in (_SECRET, _TOKEN, _RAW_RESPONSE, _PROVIDER_URL):
        assert marker not in serialized

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/evidence-admission-authorizations/{authorization_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "authorized"
    assert rows[0]["sequence_number"] == 1
    assert rows[0]["prior_receipt_hash"] is None

    fetched = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/evidence-admission-authorizations/{authorization_id}",
        headers=_headers(requester_id),
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["authorization_hash"] == body["authorization_hash"]

    replay = _authorize(
        profile_id,
        v_body["id"],
        claim_id,
        requester_id,
        key="phase-w-authorize-current",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == authorization_id
    changed_replay = _authorize(
        profile_id,
        v_body["id"],
        claim_id,
        requester_id,
        key="phase-w-authorize-current",
        reason="Attempt to change an immutable completed authorization using the same request key.",
    )
    assert changed_replay.status_code == 409, changed_replay.text

    _, other_requester, _ = _seed_tenant("phase-w-other")
    hidden = _authorize(
        profile_id,
        v_body["id"],
        claim_id,
        other_requester,
        key="phase-w-other-tenant",
    )
    assert hidden.status_code == 404, hidden.text

    with TestingSessionLocal() as db:
        assert db.query(Document).count() == documents_before
        assert db.query(Claim).count() == claims_before
        claim_after = db.get(Claim, claim_id)
        assert claim_after is not None
        assert claim_after.status == status_before
        assert db.query(ExternalDocumentSourceEvidenceAdmissionAuthorization).count() == 1
        assert db.query(ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt).count() == 1
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.action == "EXTERNAL_DOCUMENT_SOURCE_EVIDENCE_ADMISSION_AUTHORIZED")
            .all()
        )
        assert len(audits) == 1
        audit_text = json.dumps(
            [{"new": row.new_values, "details": row.details} for row in audits], sort_keys=True
        )
        for marker in (_SECRET, _TOKEN, _RAW_RESPONSE, _PROVIDER_URL, "storage_object_key"):
            assert marker not in audit_text


def test_phase_w_rejects_stale_changed_and_soft_deleted_claim() -> None:
    upstream, v_adapter, unchanged_body = _unchanged_phase_v()
    requester_id = upstream[0]
    profile_id = upstream[1]
    u_body = upstream[9]
    claim_id = _seed_claim(requester_id, "stale")

    v_adapter.result = ExactItemMetadataResult(
        found=True,
        item=replace(_baseline_projection(), byte_size=_baseline_projection().byte_size + 1),
    )
    newer = _observe(profile_id, u_body["id"], requester_id, key="phase-w-v-newer-changed")
    assert newer.status_code == 201, newer.text
    assert newer.json()["result_status"] == "changed"

    stale = _authorize(
        profile_id,
        unchanged_body["id"],
        claim_id,
        requester_id,
        key="phase-w-stale",
    )
    assert stale.status_code == 409, stale.text
    changed = _authorize(
        profile_id,
        newer.json()["id"],
        claim_id,
        requester_id,
        key="phase-w-changed",
    )
    assert changed.status_code == 409, changed.text

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        assert claim is not None
        claim.deleted_at = datetime.now(timezone.utc)
        db.commit()
    deleted = _authorize(
        profile_id,
        newer.json()["id"],
        claim_id,
        requester_id,
        key="phase-w-deleted-claim",
    )
    assert deleted.status_code == 404, deleted.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceEvidenceAdmissionAuthorization).count() == 0

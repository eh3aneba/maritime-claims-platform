from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_change_detection_service import (
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
)
from app.modules.external_document_sources.sftp_generation3_restaging_models import (
    ExternalDocumentSourceSftpGeneration3Restaging,
)
from app.modules.users.models import User
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_change_detection import _StatAdapter
from tests.test_external_document_source_sftp_generation3_change_detection import (
    _completed_phase_q,
    _generation_3_baseline,
    _observe,
    setup_function as _r_setup,
    teardown_function as _r_teardown,
)


_AUTH_REASON = (
    "Authorize this exact latest unchanged SFTP generation-3 file version "
    "for later human-controlled admission to this Claim."
)


def setup_function() -> None:
    _r_setup()


def teardown_function() -> None:
    _r_teardown()


def _seed_claim(actor_id: UUID, suffix: str = "s") -> UUID:
    with TestingSessionLocal() as db:
        actor = db.get(User, actor_id)
        assert actor is not None
        vessel = Vessel(
            organization_id=actor.organization_id,
            name=f"Phase S Vessel {suffix}",
            imo_number=None,
        )
        db.add(vessel)
        db.flush()
        claim = Claim(
            organization_id=actor.organization_id,
            vessel_id=vessel.id,
            claim_reference=f"H&M-S-{suffix}",
            incident_date=date(2026, 9, 1),
            notification_date=date(2026, 9, 2),
            incident_description="Phase S SFTP Evidence authorization acceptance fixture.",
        )
        db.add(claim)
        db.commit()
        return claim.id


def _unchanged_phase_r(seed: str):
    chain = _completed_phase_q(seed)
    adapter = _StatAdapter(
        mode="unchanged",
        baseline=_generation_3_baseline(chain),
    )
    register_external_document_source_sftp_exact_file_metadata_adapter(adapter)
    response = _observe(chain, key=f"{seed}-r-unchanged")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "unchanged"
    chain["generation3_change_detection_id"] = response.json()["id"]
    return chain, adapter, response.json()


def _authorize(
    chain: dict,
    observation_id: str,
    claim_id: UUID,
    *,
    key: str,
    reason: str = _AUTH_REASON,
    actor_id=None,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-generation-3-change-detections/{observation_id}/"
            f"claims/{claim_id}/evidence-admission-authorizations"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_phase_s_authorizes_latest_unchanged_observation_with_zero_io() -> None:
    chain, adapter, r_body = _unchanged_phase_r("sftp-phase-s-success")
    claim_id = _seed_claim(chain["requester_id"], "success")

    provider_calls_before = len(adapter.calls)
    put_before = chain["p_store"].put_calls
    head_before = chain["p_store"].head_calls
    get_before = chain["p_store"].get_calls
    read_before = len(chain["p_read_adapter"].calls)

    with TestingSessionLocal() as db:
        documents_before = db.query(Document).count()
        claims_before = db.query(Claim).count()
        status_before = db.get(Claim, claim_id).status
        q = db.get(
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
            UUID(chain["generation3_checkpoint_advancement_id"]),
        )
        p = db.get(
            ExternalDocumentSourceSftpGeneration3Restaging,
            UUID(chain["generation3_restaging_id"]),
        )
        assert q is not None
        assert p is not None
        expected_sha = q.content_sha256
        expected_storage_hash = q.storage_object_key_hash
        expected_candidate_proof = p.content_proof_hash

    forbidden = _authorize(
        chain,
        r_body["id"],
        claim_id,
        key="s-forbidden",
        extra={
            "hostname": "caller.invalid",
            "remote_path": "/caller/path",
            "storage_key": "caller/storage",
            "content": "caller-content",
            "credential": "caller-secret",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert len(adapter.calls) == provider_calls_before

    response = _authorize(
        chain,
        r_body["id"],
        claim_id,
        key="s-authorize-current",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    authorization_id = body["id"]

    assert body["status"] == "authorized"
    assert body["claim_id"] == str(claim_id)
    assert body["generation3_change_detection_id"] == r_body["id"]
    assert (
        body["generation3_checkpoint_advancement_id"]
        == chain["generation3_checkpoint_advancement_id"]
    )
    assert body["generation3_restaging_id"] == chain["generation3_restaging_id"]
    assert body["provider_kind"] == "sftp"
    assert body["authorized_projection_hash"] == r_body["observed_projection_hash"]
    assert body["authorized_entry_hash"] == r_body["baseline_entry_hash"]
    assert (
        body["authorized_relative_path_hash"]
        == r_body["baseline_relative_path_hash"]
    )
    assert body["authorized_byte_size"] == r_body["observed_byte_size"]
    assert body["authorized_metadata_id_hash"] == r_body["observed_metadata_id_hash"]
    assert body["authorized_content_sha256"] == expected_sha
    assert body["authorized_storage_object_key_hash"] == expected_storage_hash
    assert body["candidate_content_proof_hash"] == expected_candidate_proof
    assert body["observation_completion_hash"] == r_body["completion_hash"]

    for field in (
        "upstream_generation3_checkpoint_completed",
        "upstream_generation3_observation_completed",
        "latest_generation3_observation_confirmed",
        "remote_version_current_at_authorization",
        "human_authorization_recorded",
    ):
        assert body[field] is True
    for field in (
        "credential_stored",
        "session_stored",
        "provider_network_performed",
        "ssh_transport_performed",
        "authentication_performed",
        "sftp_session_opened",
        "remote_content_transiently_observed",
        "remote_list_performed",
        "remote_stat_performed",
        "remote_read_performed",
        "remote_write_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_reconciliation_performed",
        "durable_content_staged",
        "checkpoint_created",
        "checkpoint_advanced",
        "document_created",
        "evidence_admitted",
        "content_parsed",
        "content_extracted",
        "processing_enqueued",
        "ai_executed",
        "claim_mutated",
        "background_sync_started",
    ):
        assert body[field] is False

    assert len(adapter.calls) == provider_calls_before
    assert chain["p_store"].put_calls == put_before
    assert chain["p_store"].head_calls == head_before
    assert chain["p_store"].get_calls == get_before
    assert len(chain["p_read_adapter"].calls) == read_before

    serialized = json.dumps(body, sort_keys=True)
    for forbidden_field in (
        "storage_object_key",
        "hostname",
        "remote_path",
        "remote_root_path",
        "reference_name",
        "reference_namespace",
        "content",
        "credential",
        "stored_etag",
    ):
        assert forbidden_field not in body
        assert forbidden_field not in serialized

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-evidence-admission-authorizations/{authorization_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    assert len(receipts.json()) == 1
    assert receipts.json()[0]["event_type"] == "authorized"

    fetched = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-evidence-admission-authorizations/{authorization_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["authorization_hash"] == body["authorization_hash"]

    replay = _authorize(
        chain,
        r_body["id"],
        claim_id,
        key="s-authorize-current",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == authorization_id

    changed_replay = _authorize(
        chain,
        r_body["id"],
        claim_id,
        key="s-authorize-current",
        reason="Attempt to alter a completed immutable SFTP admission authorization.",
    )
    assert changed_replay.status_code == 409, changed_replay.text

    _, other_requester, _, _ = _seed_tenant("sftp-phase-s-other")
    hidden = _authorize(
        chain,
        r_body["id"],
        claim_id,
        key="s-other-tenant",
        actor_id=other_requester,
    )
    assert hidden.status_code == 404, hidden.text

    with TestingSessionLocal() as db:
        assert db.query(Document).count() == documents_before
        assert db.query(Claim).count() == claims_before
        assert db.get(Claim, claim_id).status == status_before
        assert (
            db.query(ExternalDocumentSourceSftpEvidenceAdmissionAuthorization).count()
            == 1
        )
        assert (
            db.query(
                ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt
            ).count()
            == 1
        )
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.action
                == "EXTERNAL_DOCUMENT_SOURCE_SFTP_EVIDENCE_ADMISSION_AUTHORIZED"
            )
            .all()
        )
        assert len(audits) == 1
        audit_text = json.dumps(
            [
                {"new": row.new_values, "details": row.details}
                for row in audits
            ],
            sort_keys=True,
        )
        assert "storage_object_key" not in audit_text
        assert "caller-secret" not in audit_text


def test_phase_s_rejects_stale_changed_missing_and_deleted_claim() -> None:
    chain, adapter, unchanged = _unchanged_phase_r("sftp-phase-s-stale")
    claim_id = _seed_claim(chain["requester_id"], "stale")

    adapter.mode = "changed"
    newer_changed = _observe(chain, key="s-newer-changed")
    assert newer_changed.status_code == 201, newer_changed.text
    assert newer_changed.json()["result_status"] == "changed"

    stale = _authorize(
        chain,
        unchanged["id"],
        claim_id,
        key="s-stale",
    )
    assert stale.status_code == 409, stale.text

    changed = _authorize(
        chain,
        newer_changed.json()["id"],
        claim_id,
        key="s-changed",
    )
    assert changed.status_code == 409, changed.text

    missing_chain = _completed_phase_q("sftp-phase-s-missing")
    missing_adapter = _StatAdapter(
        mode="missing",
        baseline=_generation_3_baseline(missing_chain),
    )
    register_external_document_source_sftp_exact_file_metadata_adapter(
        missing_adapter
    )
    missing_r = _observe(missing_chain, key="s-missing-r")
    assert missing_r.status_code == 201, missing_r.text
    assert missing_r.json()["result_status"] == "missing"
    missing_claim = _seed_claim(missing_chain["requester_id"], "missing")
    missing_auth = _authorize(
        missing_chain,
        missing_r.json()["id"],
        missing_claim,
        key="s-missing",
    )
    assert missing_auth.status_code == 409, missing_auth.text

    deleted_chain, _deleted_adapter, deleted_r = _unchanged_phase_r(
        "sftp-phase-s-deleted"
    )
    deleted_claim = _seed_claim(deleted_chain["requester_id"], "deleted")
    with TestingSessionLocal() as db:
        claim = db.get(Claim, deleted_claim)
        assert claim is not None
        claim.deleted_at = datetime.now(timezone.utc)
        db.commit()

    deleted = _authorize(
        deleted_chain,
        deleted_r["id"],
        deleted_claim,
        key="s-deleted",
    )
    assert deleted.status_code == 404, deleted.text


def test_phase_s_authorization_and_receipt_tamper_fail_closed() -> None:
    chain, adapter, r_body = _unchanged_phase_r("sftp-phase-s-tamper")
    claim_id = _seed_claim(chain["requester_id"], "tamper")
    response = _authorize(
        chain,
        r_body["id"],
        claim_id,
        key="s-tamper-auth",
    )
    assert response.status_code == 201, response.text
    authorization_id = UUID(response.json()["id"])
    calls_before = len(adapter.calls)

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
            authorization_id,
        )
        assert row is not None
        original_hash = row.authorization_hash
        row.authorization_hash = "a" * 64
        db.commit()

    tampered = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-evidence-admission-authorizations/{authorization_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered.status_code == 409, tampered.text
    assert len(adapter.calls) == calls_before

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
            authorization_id,
        )
        row.authorization_hash = original_hash
        receipt = (
            db.query(ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt)
            .filter(
                ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt.authorization_id
                == authorization_id
            )
            .one()
        )
        receipt.decision_hash = "b" * 64
        db.commit()

    tampered_receipt = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-evidence-admission-authorizations/{authorization_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered_receipt.status_code == 409, tampered_receipt.text
    assert len(adapter.calls) == calls_before

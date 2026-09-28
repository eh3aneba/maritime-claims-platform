from __future__ import annotations

import json
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.documents.malware import MalwareScanResult, MalwareScanVerdict
from app.modules.documents.models import Document, DocumentMalwareScanStatus
from app.modules.processing.models import DocumentProcessingJob
from app.modules.external_document_sources import (
    sftp_evidence_admission_execution_service as admission_service,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.external_document_sources.sftp_evidence_admission_execution_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionExecution,
    ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceipt,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers
from tests.test_external_document_source_sftp_change_detection import _StatAdapter
from tests.test_external_document_source_sftp_evidence_admission_authorization import (
    _authorize,
    _seed_claim,
    _unchanged_phase_r,
    setup_function as _s_setup,
    teardown_function as _s_teardown,
)
from tests.test_external_document_source_sftp_generation3_change_detection import (
    _generation_3_baseline,
    _observe,
)


_EXECUTION_REASON = (
    "Consume the exact current human-authorized SFTP file version into one "
    "canonical initial Evidence Document after fresh custody and security checks."
)


def setup_function() -> None:
    _s_setup()


def teardown_function() -> None:
    _s_teardown()


def _authorized_phase_s(seed: str):
    chain, adapter, r_body = _unchanged_phase_r(seed)
    claim_id = _seed_claim(chain["requester_id"], seed)
    authorization = _authorize(
        chain,
        r_body["id"],
        claim_id,
        key=f"{seed}-s-auth",
    )
    assert authorization.status_code == 201, authorization.text
    return chain, adapter, r_body, claim_id, authorization.json()


def _enable_clean_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admission_service.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(
        admission_service,
        "validate_file_signature",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        admission_service,
        "scan_file",
        lambda *_args, **_kwargs: MalwareScanResult(
            verdict=MalwareScanVerdict.CLEAN
        ),
    )


def _execute(
    chain: dict,
    authorization_id: str,
    *,
    key: str,
    reason: str = _EXECUTION_REASON,
    actor_id=None,
    extra: dict | None = None,
):
    payload = {
        "request_key": key,
        "reason": reason,
        "document_type": "External SFTP survey evidence",
        "confidentiality_level": "confidential",
    }
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-evidence-admission-authorizations/{authorization_id}/executions"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_phase_t_consumes_one_authorization_and_creates_one_document_without_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _r_body, claim_id, authorization = _authorized_phase_s(
        "sftp-phase-t-success"
    )
    _enable_clean_admission(monkeypatch)

    with TestingSessionLocal() as db:
        documents_before = db.query(Document).count()
    metadata_calls_before = len(adapter.calls)
    staged_gets_before = chain["p_store"].get_calls
    staged_heads_before = chain["p_store"].head_calls
    remote_reads_before = len(chain["p_read_adapter"].calls)

    forbidden = _execute(
        chain,
        authorization["id"],
        key="t-forbidden",
        extra={
            "hostname": "caller.invalid",
            "remote_path": "/caller/path",
            "storage_key": "caller/storage",
            "content": "caller-content",
            "credential": "caller-secret",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert len(adapter.calls) == metadata_calls_before
    assert chain["p_store"].get_calls == staged_gets_before

    response = _execute(
        chain,
        authorization["id"],
        key="t-admit-success",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    execution_id = body["id"]
    document_id = body["document_id"]

    assert body["status"] == "admitted"
    assert body["authorization_id"] == authorization["id"]
    assert body["claim_id"] == str(claim_id)
    assert body["provider_kind"] == "sftp"
    assert body["fresh_projection_hash"] == authorization["authorized_projection_hash"]
    assert body["staged_content_sha256"] == authorization["authorized_content_sha256"]
    assert (
        body["staged_storage_object_key_hash"]
        == authorization["authorized_storage_object_key_hash"]
    )
    assert body["document_file_hash"] == body["staged_content_sha256"]
    assert body["document_file_size_bytes"] == body["staged_content_byte_count"]

    for field in (
        "upstream_authorization_verified",
        "authorization_single_use_consumed",
        "latest_generation3_observation_confirmed",
        "fresh_exact_file_metadata_read_performed",
        "fresh_remote_version_current",
        "staged_storage_read_performed",
        "staged_content_integrity_verified",
        "malware_scan_completed",
        "canonical_document_write_completed",
        "document_created",
        "evidence_admitted",
        "admission_execution_performed",
        "secret_resolution_performed",
        "provider_network_performed",
        "ssh_transport_performed",
        "host_key_verification_performed",
        "host_key_verified",
        "authentication_performed",
        "authentication_succeeded",
        "sftp_session_opened",
        "sftp_session_closed",
        "remote_stat_performed",
    ):
        assert body[field] is True
    for field in (
        "remote_list_performed",
        "remote_content_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "staged_storage_write_performed",
        "staged_storage_delete_performed",
        "content_parsed",
        "content_extracted",
        "processing_enqueued",
        "ai_executed",
        "claim_mutated",
        "checkpoint_advanced",
        "background_sync_started",
    ):
        assert body[field] is False

    assert len(adapter.calls) == metadata_calls_before + 1
    assert chain["p_store"].head_calls > staged_heads_before
    assert chain["p_store"].get_calls > staged_gets_before
    assert len(chain["p_read_adapter"].calls) == remote_reads_before

    serialized = json.dumps(body, sort_keys=True)
    for forbidden_marker in (
        "storage_object_key",
        "remote_path",
        "remote_root_path",
        "reference_name",
        "reference_namespace",
        "content",
        "credential",
        "stored_etag",
    ):
        assert forbidden_marker not in body
        assert forbidden_marker not in serialized

    with TestingSessionLocal() as db:
        assert db.query(Document).count() == documents_before + 1
        document = db.get(Document, UUID(document_id))
        assert document is not None
        assert document.claim_id == claim_id
        assert document.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        assert document.document_family_id == document.id
        assert db.query(DocumentProcessingJob).filter(
            DocumentProcessingJob.document_id == document.id
        ).count() == 0
        assert db.query(
            ExternalDocumentSourceSftpEvidenceAdmissionExecution
        ).count() == 1
        assert db.query(
            ExternalDocumentSourceSftpEvidenceAdmissionExecutionReceipt
        ).count() == 1
        audits = db.query(AuditLog).filter(
            AuditLog.action == "ADMIT_SFTP_EXTERNAL_DOCUMENT_SOURCE_TO_EVIDENCE"
        ).all()
        assert len(audits) == 1
        audit_text = json.dumps(
            [{"new": row.new_values, "details": row.details} for row in audits],
            sort_keys=True,
        )
        assert "storage_object_key" not in audit_text
        assert "remote_path" not in audit_text

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-evidence-admission-executions/{execution_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    assert len(receipts.json()) == 1
    assert receipts.json()[0]["event_type"] == "admitted"

    metadata_calls_after = len(adapter.calls)
    staged_gets_after = chain["p_store"].get_calls
    replay = _execute(
        chain,
        authorization["id"],
        key="t-admit-success",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert len(adapter.calls) == metadata_calls_after
    assert chain["p_store"].get_calls == staged_gets_after

    changed_replay = _execute(
        chain,
        authorization["id"],
        key="t-admit-success",
        reason=(
            "Attempt to alter the completed single-use SFTP Evidence admission "
            "execution after it was committed."
        ),
    )
    assert changed_replay.status_code == 409, changed_replay.text

    retry = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/retry",
        headers=_headers(chain["requester_id"]),
    )
    assert retry.status_code == 409, retry.text
    assert "processing" in retry.json()["detail"].lower()


def test_phase_t_rejects_stale_authorization_before_fresh_stat_or_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _r_body, _claim_id, authorization = _authorized_phase_s(
        "sftp-phase-t-stale"
    )
    _enable_clean_admission(monkeypatch)

    newer = _observe(chain, key="t-newer-r")
    assert newer.status_code == 201, newer.text
    assert newer.json()["result_status"] == "unchanged"

    calls_before = len(adapter.calls)
    gets_before = chain["p_store"].get_calls
    with TestingSessionLocal() as db:
        documents_before = db.query(Document).count()

    rejected = _execute(
        chain,
        authorization["id"],
        key="t-stale-exec",
    )
    assert rejected.status_code == 409, rejected.text
    assert "stale" in rejected.json()["detail"].lower()
    assert len(adapter.calls) == calls_before
    assert chain["p_store"].get_calls == gets_before
    with TestingSessionLocal() as db:
        assert db.query(Document).count() == documents_before
        assert db.query(
            ExternalDocumentSourceSftpEvidenceAdmissionExecution
        ).count() == 0


def test_phase_t_rejects_fresh_metadata_drift_before_staged_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _r_body, _claim_id, authorization = _authorized_phase_s(
        "sftp-phase-t-drift"
    )
    _enable_clean_admission(monkeypatch)
    adapter.mode = "changed"

    calls_before = len(adapter.calls)
    gets_before = chain["p_store"].get_calls
    rejected = _execute(
        chain,
        authorization["id"],
        key="t-drift-exec",
    )
    assert rejected.status_code == 409, rejected.text
    assert "changed after human authorization" in rejected.json()["detail"].lower()
    assert len(adapter.calls) == calls_before + 1
    assert chain["p_store"].get_calls == gets_before


def test_phase_t_rejects_missing_staged_object_after_currentness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _r_body, _claim_id, authorization = _authorized_phase_s(
        "sftp-phase-t-stage-missing"
    )
    _enable_clean_admission(monkeypatch)
    chain["p_store"].objects.clear()

    calls_before = len(adapter.calls)
    rejected = _execute(
        chain,
        authorization["id"],
        key="t-stage-missing",
    )
    assert rejected.status_code == 409, rejected.text
    assert "staged object is missing" in rejected.json()["detail"].lower()
    assert len(adapter.calls) == calls_before + 1

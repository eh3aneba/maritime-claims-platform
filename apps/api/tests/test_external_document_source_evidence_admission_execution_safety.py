from dataclasses import replace
from uuid import UUID

import pytest

import app.modules.external_document_sources.evidence_admission_execution_service as admission_service
from app.modules.documents.malware import MalwareScanResult, MalwareScanVerdict
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import ExactItemMetadataResult
from app.modules.external_document_sources.evidence_admission_authorization_models import (
    ExternalDocumentSourceEvidenceAdmissionAuthorization,
)
from app.modules.external_document_sources.evidence_admission_execution_models import (
    ExternalDocumentSourceEvidenceAdmissionExecution,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_evidence_admission_authorization import (
    _authorize,
    _seed_claim,
    _unchanged_phase_v,
    setup_function as _phase_w_setup,
    teardown_function as _phase_w_teardown,
)
from tests.test_external_document_source_generation_3_change_detection import _baseline_projection

_REASON = (
    "Admit the authorized external source as Claim Evidence only after all Phase X currentness, integrity, signature and malware controls pass."
)


def setup_function() -> None:
    _phase_w_setup()


def teardown_function() -> None:
    _phase_w_teardown()


def _execute(profile_id: str, authorization_id: str, actor_id, *, key: str):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/evidence-admission-authorizations/{authorization_id}/executions",
        headers=_headers(actor_id),
        json={
            "request_key": key,
            "reason": _REASON,
            "document_type": "External evidence",
            "confidentiality_level": "restricted",
        },
    )


def _patch_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admission_service.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(admission_service, "validate_file_signature", lambda *_args, **_kwargs: None)


def test_phase_x_rejects_remote_drift_before_staged_object_read(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream, metadata_adapter, observation = _unchanged_phase_v()
    actor_id = upstream[0]
    profile_id = upstream[1]
    store = upstream[14]
    claim_id = _seed_claim(actor_id, "x-remote-drift")
    authorization = _authorize(
        profile_id,
        observation["id"],
        claim_id,
        actor_id,
        key="phase-x-auth-remote-drift",
    )
    assert authorization.status_code == 201, authorization.text
    _patch_signature(monkeypatch)
    monkeypatch.setattr(
        admission_service,
        "scan_file",
        lambda *_args, **_kwargs: MalwareScanResult(verdict=MalwareScanVerdict.CLEAN),
    )

    baseline = _baseline_projection()
    metadata_adapter.result = ExactItemMetadataResult(
        found=True,
        item=replace(baseline, byte_size=baseline.byte_size + 1),
    )
    gets_before = store.get_calls
    with TestingSessionLocal() as db:
        documents_before = db.query(Document).count()

    response = _execute(
        profile_id,
        authorization.json()["id"],
        actor_id,
        key="phase-x-exec-remote-drift",
    )
    assert response.status_code == 409, response.text
    assert "changed" in response.json()["detail"].lower()
    assert store.get_calls == gets_before
    with TestingSessionLocal() as db:
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceEvidenceAdmissionExecution).count() == 0


def test_phase_x_rejects_malware_without_creating_document(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream, _metadata_adapter, observation = _unchanged_phase_v()
    actor_id = upstream[0]
    profile_id = upstream[1]
    claim_id = _seed_claim(actor_id, "x-malware")
    authorization = _authorize(
        profile_id,
        observation["id"],
        claim_id,
        actor_id,
        key="phase-x-auth-malware",
    )
    assert authorization.status_code == 201, authorization.text
    _patch_signature(monkeypatch)
    monkeypatch.setattr(
        admission_service,
        "scan_file",
        lambda *_args, **_kwargs: MalwareScanResult(
            verdict=MalwareScanVerdict.INFECTED,
            threat_name="test-threat",
            raw_response="secret scanner response must not persist",
        ),
    )
    with TestingSessionLocal() as db:
        documents_before = db.query(Document).count()

    response = _execute(
        profile_id,
        authorization.json()["id"],
        actor_id,
        key="phase-x-exec-malware",
    )
    assert response.status_code == 409, response.text
    assert "malware" in response.json()["detail"].lower()
    assert "test-threat" not in response.text
    assert "secret scanner response" not in response.text
    with TestingSessionLocal() as db:
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceEvidenceAdmissionExecution).count() == 0


def test_phase_x_hides_cross_tenant_authorization_and_detects_authorization_tamper(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream, _metadata_adapter, observation = _unchanged_phase_v()
    actor_id = upstream[0]
    profile_id = upstream[1]
    claim_id = _seed_claim(actor_id, "x-tenant-tamper")
    authorization = _authorize(
        profile_id,
        observation["id"],
        claim_id,
        actor_id,
        key="phase-x-auth-tenant-tamper",
    )
    assert authorization.status_code == 201, authorization.text
    authorization_id = authorization.json()["id"]
    _patch_signature(monkeypatch)

    _, other_actor, _ = _seed_tenant("phase-x-other-tenant")
    hidden = _execute(
        profile_id,
        authorization_id,
        other_actor,
        key="phase-x-cross-tenant",
    )
    assert hidden.status_code == 404, hidden.text

    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceEvidenceAdmissionAuthorization, UUID(authorization_id))
        assert row is not None
        row.authorization_hash = "0" * 64
        db.commit()
    rejected = _execute(
        profile_id,
        authorization_id,
        actor_id,
        key="phase-x-tampered-auth",
    )
    assert rejected.status_code == 409, rejected.text
    assert "hash" in rejected.json()["detail"].lower() or "integrity" in rejected.json()["detail"].lower()
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceEvidenceAdmissionExecution).count() == 0
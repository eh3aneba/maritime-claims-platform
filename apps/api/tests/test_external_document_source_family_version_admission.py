from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

import app.modules.external_document_sources.family_version_admission_service as aa_service
from app.modules.documents.malware import MalwareScanResult, MalwareScanVerdict
from app.modules.documents.models import (
    ConfidentialityLevel,
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.checkpoint_generation_models import (
    ExternalDocumentSourceCheckpointGenerationExecution,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.family_version_admission_models import (
    ExternalDocumentSourceFamilyVersionAdmissionAuthorization,
    ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt,
    ExternalDocumentSourceFamilyVersionAdmissionExecution,
    ExternalDocumentSourceFamilyVersionAdmissionReceipt,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.processing.models import DocumentProcessingJob
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import _ChangeAdapter
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_evidence_family_binding import (
    _admit,
    _bind,
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_successor_change_detection import (
    _generation2_projection,
    _observe as _observe_s,
)
from tests.test_external_document_source_successor_versioned_restaging import (
    _T_BODY,
    _TReadAdapter,
    _restage_successor,
)

_AUTH_REASON = (
    "Authorize this exact staged later remote version for admission into the "
    "existing immutable external Evidence family."
)
_EXEC_REASON = (
    "Admit the separately authorized staged remote version as the next "
    "immutable Document version in the existing external Evidence family."
)
_RELEASE_REASON = (
    "Authorize local deterministic processing for the exact current v1 Evidence "
    "before a later source version supersedes it."
)
_V2_BODY = b"phase-aa-later-version-payload-" * 64
_V2_VERSION = "e" * 64
_V2_MODIFIED = datetime(2026, 9, 19, 15, 30, tzinfo=UTC)


def setup_function() -> None:
    _phase_y_setup()


def teardown_function() -> None:
    _phase_y_teardown()


def _enable_clean_aa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aa_service.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(
        aa_service,
        "validate_file_signature",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        aa_service,
        "scan_file",
        lambda *_args, **_kwargs: MalwareScanResult(
            verdict=MalwareScanVerdict.CLEAN
        ),
    )


def _authorize_aa(
    profile_id: str,
    binding_id: str,
    candidate_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _AUTH_REASON,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/evidence-family-bindings/{binding_id}"
            f"/version-admission-authorizations/{candidate_id}"
        ),
        headers=_headers(actor_id),
        json=payload,
    )


def _aa_admit(
    profile_id: str,
    binding_id: str,
    authorization_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _EXEC_REASON,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/evidence-family-bindings/{binding_id}"
            f"/version-admissions/{authorization_id}"
        ),
        headers=_headers(actor_id),
        json=payload,
    )


def _latest_phase_r(
    profile_id: str,
) -> ExternalDocumentSourceCheckpointGenerationExecution:
    with TestingSessionLocal() as db:
        row = db.scalar(
            select(ExternalDocumentSourceCheckpointGenerationExecution)
            .where(
                ExternalDocumentSourceCheckpointGenerationExecution.profile_id
                == UUID(profile_id),
                ExternalDocumentSourceCheckpointGenerationExecution.status
                == "completed",
            )
            .order_by(
                ExternalDocumentSourceCheckpointGenerationExecution.created_at.desc(),
                ExternalDocumentSourceCheckpointGenerationExecution.id.desc(),
            )
            .limit(1)
        )
        assert row is not None
        db.expunge(row)
        return row


def _later_candidate(
    *,
    profile_id: str,
    actor_id: UUID,
    suffix: str,
    body: bytes = _V2_BODY,
    version: str = _V2_VERSION,
    modified: datetime = _V2_MODIFIED,
):
    r_row = _latest_phase_r(profile_id)
    projection = _generation2_projection(
        size=len(body),
        version=version,
        modified=modified,
    )

    metadata_adapter = _ChangeAdapter()
    metadata_adapter.result = ExactItemMetadataResult(
        found=True,
        item=projection,
    )
    register_external_document_source_change_detection_adapter(
        "sharepoint",
        "graph_drive_item_metadata_read_v1",
        metadata_adapter,
    )
    s = _observe_s(
        profile_id,
        str(r_row.id),
        actor_id,
        key=f"phase-aa-s-{suffix}",
    )
    assert s.status_code == 201, s.text
    assert s.json()["result_status"] == "changed"

    content_adapter = _TReadAdapter(
        content=body,
        version=version,
        media="application/pdf",
    )
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        content_adapter,
    )
    t = _restage_successor(
        profile_id,
        s.json()["id"],
        actor_id,
        key=f"phase-aa-t-{suffix}",
    )
    assert t.status_code == 201, t.text
    assert t.json()["status"] == "completed"
    return t.json(), metadata_adapter, projection


def _bound_v1(monkeypatch: pytest.MonkeyPatch, suffix: str):
    actor_id, profile_id, claim_id, initial_execution, _adapter, _store = _admit(
        monkeypatch,
        suffix,
    )
    binding = _bind(
        profile_id,
        initial_execution["id"],
        actor_id,
        key=f"phase-aa-y-{suffix}",
    )
    assert binding.status_code == 201, binding.text
    return (
        actor_id,
        profile_id,
        claim_id,
        initial_execution,
        binding.json(),
    )


def test_phase_aa_authorizes_then_admits_exact_later_version_without_inheriting_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, initial_execution, binding = _bound_v1(
        monkeypatch,
        "success",
    )
    v1_id = UUID(initial_execution["document_id"])

    release = client.post(
        f"/api/v1/claims/{claim_id}/documents/{v1_id}/processing/release",
        headers=_headers(actor_id),
        json={
            "request_key": "phase-aa-v1-release",
            "reason": _RELEASE_REASON,
        },
    )
    assert release.status_code == 201, release.text

    candidate, metadata_adapter, _projection = _later_candidate(
        profile_id=profile_id,
        actor_id=actor_id,
        suffix="success",
    )

    forbidden_auth = _authorize_aa(
        profile_id,
        binding["id"],
        candidate["id"],
        actor_id,
        key="phase-aa-auth-forbidden",
        extra={
            "claim_id": str(claim_id),
            "processing_authorized": True,
        },
    )
    assert forbidden_auth.status_code == 422, forbidden_auth.text

    calls_before_auth = metadata_adapter.calls
    authorization = _authorize_aa(
        profile_id,
        binding["id"],
        candidate["id"],
        actor_id,
        key="phase-aa-auth-v2",
    )
    assert authorization.status_code == 201, authorization.text
    auth = authorization.json()
    assert auth["status"] == "authorized"
    assert auth["expected_prior_document_id"] == str(v1_id)
    assert auth["expected_prior_version_number"] == 1
    assert auth["document_family_id"] == binding["document_family_id"]
    assert auth["stable_source_item_hash"] == binding["stable_source_item_hash"]
    assert auth["processing_enqueued"] is False
    assert auth["ai_executed"] is False
    assert auth["remote_metadata_read_performed"] is False
    assert metadata_adapter.calls == calls_before_auth

    with TestingSessionLocal() as db:
        v1 = db.get(Document, v1_id)
        assert v1 is not None and v1.is_current is True
        assert db.query(DocumentProcessingJob).count() == 0
        auth_receipts = (
            db.query(ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt)
            .filter(
                ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt.authorization_id
                == UUID(auth["id"])
            )
            .all()
        )
        assert len(auth_receipts) == 1
        assert auth_receipts[0].event_type == "authorized"

    auth_replay = _authorize_aa(
        profile_id,
        binding["id"],
        candidate["id"],
        actor_id,
        key="phase-aa-auth-v2",
    )
    assert auth_replay.status_code == 201, auth_replay.text
    assert auth_replay.json()["id"] == auth["id"]

    _enable_clean_aa(monkeypatch)
    forbidden_exec = _aa_admit(
        profile_id,
        binding["id"],
        auth["id"],
        actor_id,
        key="phase-aa-exec-forbidden",
        extra={
            "document_family_id": "caller-controlled",
            "ai_processing_authorized": True,
        },
    )
    assert forbidden_exec.status_code == 422, forbidden_exec.text

    calls_before_exec = metadata_adapter.calls
    admitted = _aa_admit(
        profile_id,
        binding["id"],
        auth["id"],
        actor_id,
        key="phase-aa-admit-v2",
    )
    assert admitted.status_code == 201, admitted.text
    body = admitted.json()
    assert body["status"] == "admitted"
    assert body["prior_document_id"] == str(v1_id)
    assert body["prior_version_number"] == 1
    assert body["new_version_number"] == 2
    assert body["document_family_id"] == binding["document_family_id"]
    assert body["stable_source_item_hash"] == binding["stable_source_item_hash"]
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert metadata_adapter.calls == calls_before_exec + 1

    v2_id = UUID(body["new_document_id"])
    with TestingSessionLocal() as db:
        v1 = db.get(Document, v1_id)
        v2 = db.get(Document, v2_id)
        assert v1 is not None and v2 is not None
        assert v1.document_family_id == v2.document_family_id
        assert v1.version_number == 1
        assert v1.is_current is False
        assert v1.superseded_by_id == actor_id
        assert v2.version_number == 2
        assert v2.is_current is True
        assert v2.supersedes_document_id == v1.id
        assert v2.processing_status == DocumentProcessingStatus.UPLOADED
        assert v2.file_hash == body["new_document_file_hash"]
        assert (
            db.query(Document)
            .filter(
                Document.document_family_id == v2.document_family_id,
                Document.is_current.is_(True),
                Document.deleted_at.is_(None),
            )
            .count()
            == 1
        )
        assert db.query(DocumentProcessingJob).count() == 0
        receipts = (
            db.query(ExternalDocumentSourceFamilyVersionAdmissionReceipt)
            .filter(
                ExternalDocumentSourceFamilyVersionAdmissionReceipt.execution_id
                == UUID(body["id"])
            )
            .all()
        )
        assert len(receipts) == 1
        assert receipts[0].event_type == "admitted"

    old_retry = client.post(
        f"/api/v1/claims/{claim_id}/documents/{v1_id}/processing/retry",
        headers=_headers(actor_id),
    )
    assert old_retry.status_code == 409, old_retry.text

    new_summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{v2_id}/processing",
        headers=_headers(actor_id),
    )
    assert new_summary.status_code == 200, new_summary.text
    assert new_summary.json()["processing_release_required"] is True
    assert new_summary.json()["processing_release_status"] == "required"

    new_retry = client.post(
        f"/api/v1/claims/{claim_id}/documents/{v2_id}/processing/retry",
        headers=_headers(actor_id),
    )
    assert new_retry.status_code == 409, new_retry.text

    replay = _aa_admit(
        profile_id,
        binding["id"],
        auth["id"],
        actor_id,
        key="phase-aa-admit-v2",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == body["id"]
    assert replay.json()["new_document_id"] == str(v2_id)
    assert metadata_adapter.calls == calls_before_exec + 1

    altered = _aa_admit(
        profile_id,
        binding["id"],
        auth["id"],
        actor_id,
        key="phase-aa-admit-v2-altered",
    )
    assert altered.status_code == 409, altered.text

    v2_release = client.post(
        f"/api/v1/claims/{claim_id}/documents/{v2_id}/processing/release",
        headers=_headers(actor_id),
        json={
            "request_key": "phase-aa-v2-release",
            "reason": (
                "Authorize local deterministic processing for the exact current "
                "v2 Evidence after separate AA admission."
            ),
        },
    )
    assert v2_release.status_code == 201, v2_release.text
    assert v2_release.json()["document_id"] == str(v2_id)
    assert v2_release.json()["document_version_number"] == 2
    assert v2_release.json()["ai_processing_authorized"] is False

    v2_retry = client.post(
        f"/api/v1/claims/{claim_id}/documents/{v2_id}/processing/retry",
        headers=_headers(actor_id),
    )
    assert v2_retry.status_code == 202, v2_retry.text


def test_phase_aa_rejects_stale_candidate_before_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "stale-candidate",
    )
    candidate, _adapter, _projection = _later_candidate(
        profile_id=profile_id,
        actor_id=actor_id,
        suffix="stale-candidate-v2",
    )

    # A newer observation on the same durable Phase-R source baseline makes
    # the earlier staged candidate stale before a human can authorize it.
    r_row = _latest_phase_r(profile_id)
    newer_projection = _generation2_projection(
        size=len(_V2_BODY) + 11,
        version="f" * 64,
        modified=datetime(2026, 9, 19, 16, 45, tzinfo=UTC),
    )
    newer_adapter = _ChangeAdapter()
    newer_adapter.result = ExactItemMetadataResult(
        found=True,
        item=newer_projection,
    )
    register_external_document_source_change_detection_adapter(
        "sharepoint",
        "graph_drive_item_metadata_read_v1",
        newer_adapter,
    )
    newer = _observe_s(
        profile_id,
        str(r_row.id),
        actor_id,
        key="phase-aa-newer-observation",
    )
    assert newer.status_code == 201, newer.text
    assert newer.json()["result_status"] == "changed"

    rejected = _authorize_aa(
        profile_id,
        binding["id"],
        candidate["id"],
        actor_id,
        key="phase-aa-stale-candidate-auth",
    )
    assert rejected.status_code == 409, rejected.text


def test_phase_aa_rejects_same_content_candidate_before_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, initial_execution, binding = _bound_v1(
        monkeypatch,
        "same-content",
    )
    candidate, _adapter, _projection = _later_candidate(
        profile_id=profile_id,
        actor_id=actor_id,
        suffix="same-content",
        body=_T_BODY,
        version="f" * 64,
        modified=datetime(2026, 9, 19, 16, 30, tzinfo=UTC),
    )
    rejected = _authorize_aa(
        profile_id,
        binding["id"],
        candidate["id"],
        actor_id,
        key="phase-aa-same-content-auth",
    )
    assert rejected.status_code == 409, rejected.text

    with TestingSessionLocal() as db:
        current = db.get(Document, UUID(initial_execution["document_id"]))
        assert current is not None
        assert current.claim_id == claim_id
        assert current.is_current is True
        assert current.version_number == 1
        assert db.query(ExternalDocumentSourceFamilyVersionAdmissionAuthorization).count() == 0


def test_phase_aa_cross_tenant_authorization_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "isolation",
    )
    candidate, _adapter, _projection = _later_candidate(
        profile_id=profile_id,
        actor_id=actor_id,
        suffix="isolation",
    )
    _other_org, other_admin, _other_approver = _seed_tenant(
        "phase-aa-cross-tenant"
    )
    rejected = _authorize_aa(
        profile_id,
        binding["id"],
        candidate["id"],
        other_admin,
        key="phase-aa-cross-tenant",
    )
    assert rejected.status_code == 404, rejected.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceFamilyVersionAdmissionAuthorization).count() == 0


def test_phase_aa_authorization_becomes_stale_if_current_document_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, initial_execution, binding = _bound_v1(
        monkeypatch,
        "stale-auth",
    )
    candidate, _adapter, _projection = _later_candidate(
        profile_id=profile_id,
        actor_id=actor_id,
        suffix="stale-auth",
    )
    authorization = _authorize_aa(
        profile_id,
        binding["id"],
        candidate["id"],
        actor_id,
        key="phase-aa-stale-auth-record",
    )
    assert authorization.status_code == 201, authorization.text
    auth = authorization.json()

    with TestingSessionLocal() as db:
        v1 = db.get(Document, UUID(initial_execution["document_id"]))
        assert v1 is not None
        v1.is_current = False
        now = datetime(2026, 9, 19, 18, 0, tzinfo=UTC)
        v1.superseded_at = now
        v1.superseded_by_id = actor_id
        v2 = Document(
            id=uuid4(),
            organization_id=v1.organization_id,
            claim_id=v1.claim_id,
            uploaded_by_id=actor_id,
            supersedes_document_id=v1.id,
            document_family_id=v1.document_family_id,
            version_number=2,
            is_current=True,
            replacement_reason="Simulate a racing canonical version change.",
            source_admission_note="Simulated concurrent replacement.",
            filename="simulated-v2.pdf",
            original_filename="simulated-v2.pdf",
            document_type=v1.document_type,
            mime_type="application/pdf",
            file_size_bytes=222,
            file_hash="9" * 64,
            storage_key=f"test/phase-aa-stale/{uuid4().hex}.pdf",
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
            malware_scan_status=DocumentMalwareScanStatus.CLEAN,
            malware_scanned_at=now,
        )
        db.add(v2)
        db.commit()

    _enable_clean_aa(monkeypatch)
    rejected = _aa_admit(
        profile_id,
        binding["id"],
        auth["id"],
        actor_id,
        key="phase-aa-stale-auth-exec",
    )
    assert rejected.status_code == 409, rejected.text

    with TestingSessionLocal() as db:
        current = list(
            db.scalars(
                select(Document).where(
                    Document.claim_id == claim_id,
                    Document.document_family_id
                    == UUID(binding["document_family_id"]),
                    Document.is_current.is_(True),
                    Document.deleted_at.is_(None),
                )
            ).all()
        )
        assert len(current) == 1
        assert current[0].version_number == 2
        assert db.query(ExternalDocumentSourceFamilyVersionAdmissionExecution).count() == 0


def test_phase_aa_binding_tamper_fails_before_document_version_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, initial_execution, binding = _bound_v1(
        monkeypatch,
        "tamper",
    )
    candidate, _adapter, _projection = _later_candidate(
        profile_id=profile_id,
        actor_id=actor_id,
        suffix="tamper",
    )
    authorization = _authorize_aa(
        profile_id,
        binding["id"],
        candidate["id"],
        actor_id,
        key="phase-aa-tamper-auth",
    )
    assert authorization.status_code == 201, authorization.text
    _enable_clean_aa(monkeypatch)

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceEvidenceFamilyBinding,
            UUID(binding["id"]),
        )
        assert row is not None
        row.stable_source_item_hash = "0" * 64
        db.commit()

    rejected = _aa_admit(
        profile_id,
        binding["id"],
        authorization.json()["id"],
        actor_id,
        key="phase-aa-tampered-binding",
    )
    assert rejected.status_code == 409, rejected.text

    with TestingSessionLocal() as db:
        current = db.get(Document, UUID(initial_execution["document_id"]))
        assert current is not None
        assert current.claim_id == claim_id
        assert current.version_number == 1
        assert current.is_current is True
        assert db.query(ExternalDocumentSourceFamilyVersionAdmissionExecution).count() == 0

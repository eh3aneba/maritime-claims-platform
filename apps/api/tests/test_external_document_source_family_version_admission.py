from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select

import app.modules.external_document_sources.family_version_admission_service as aa_service
from app.modules.documents.malware import MalwareScanResult, MalwareScanVerdict
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.checkpoint_generation_models import (
    ExternalDocumentSourceCheckpointGenerationExecution,
)
from app.modules.external_document_sources.family_version_admission_models import (
    ExternalDocumentSourceFamilyVersionAdmissionExecution,
    ExternalDocumentSourceFamilyVersionAdmissionReceipt,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.generation_3_change_detection_models import (
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.processing.models import DocumentProcessingJob
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import _ChangeAdapter
from tests.test_external_document_source_checkpoint_generation_3 import (
    _advance as _advance_u,
)
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_evidence_admission_authorization import (
    _authorize,
    _seed_claim,
)
from tests.test_external_document_source_evidence_admission_execution import (
    _execute as _execute_initial,
)
from tests.test_external_document_source_evidence_family_binding import (
    _admit,
    _bind,
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_generation_3_change_detection import (
    _observe as _observe_v,
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

_AA_REASON = (
    "Admit this separately authorized later remote source version as the next "
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


def _aa_admit(
    profile_id: str,
    binding_id: str,
    authorization_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _AA_REASON,
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


def _latest_phase_r(profile_id: str) -> ExternalDocumentSourceCheckpointGenerationExecution:
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


def _later_authorization(
    *,
    profile_id: str,
    claim_id: UUID,
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

    s_adapter = _ChangeAdapter()
    s_adapter.result = ExactItemMetadataResult(found=True, item=projection)
    register_external_document_source_change_detection_adapter(
        "sharepoint",
        "graph_drive_item_metadata_read_v1",
        s_adapter,
    )
    s = _observe_s(
        profile_id,
        str(r_row.id),
        actor_id,
        key=f"phase-aa-s-{suffix}",
    )
    assert s.status_code == 201, s.text
    assert s.json()["result_status"] == "changed"

    t_adapter = _TReadAdapter(
        content=body,
        version=version,
        media="application/pdf",
    )
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        t_adapter,
    )
    t = _restage_successor(
        profile_id,
        s.json()["id"],
        actor_id,
        key=f"phase-aa-t-{suffix}",
    )
    assert t.status_code == 201, t.text
    assert t.json()["status"] == "completed"

    u = _advance_u(
        profile_id,
        t.json()["id"],
        actor_id,
        key=f"phase-aa-u-{suffix}",
    )
    assert u.status_code == 201, u.text

    v_adapter = _ChangeAdapter()
    v_adapter.result = ExactItemMetadataResult(found=True, item=projection)
    register_external_document_source_change_detection_adapter(
        "sharepoint",
        "graph_drive_item_metadata_read_v1",
        v_adapter,
    )
    v = _observe_v(
        profile_id,
        u.json()["id"],
        actor_id,
        key=f"phase-aa-v-{suffix}",
    )
    assert v.status_code == 201, v.text
    assert v.json()["result_status"] == "unchanged"

    authorization = _authorize(
        profile_id,
        v.json()["id"],
        claim_id,
        actor_id,
        key=f"phase-aa-w-{suffix}",
    )
    assert authorization.status_code == 201, authorization.text
    return authorization.json(), v_adapter


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


def test_phase_aa_admits_exact_later_version_without_inheriting_processing_authority(
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
    assert release.json()["document_id"] == str(v1_id)

    authorization, v_adapter = _later_authorization(
        profile_id=profile_id,
        claim_id=claim_id,
        actor_id=actor_id,
        suffix="success",
    )
    _enable_clean_aa(monkeypatch)

    forbidden = _aa_admit(
        profile_id,
        binding["id"],
        authorization["id"],
        actor_id,
        key="phase-aa-forbidden",
        extra={
            "document_family_id": "caller-controlled",
            "processing_authorized": True,
        },
    )
    assert forbidden.status_code == 422, forbidden.text

    before_calls = v_adapter.calls
    admitted = _aa_admit(
        profile_id,
        binding["id"],
        authorization["id"],
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
    assert v_adapter.calls == before_calls + 1

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
        rows = (
            db.query(ExternalDocumentSourceFamilyVersionAdmissionReceipt)
            .filter(
                ExternalDocumentSourceFamilyVersionAdmissionReceipt.execution_id
                == UUID(body["id"])
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].event_type == "admitted"

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
        authorization["id"],
        actor_id,
        key="phase-aa-admit-v2",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == body["id"]
    assert replay.json()["new_document_id"] == str(v2_id)

    altered = _aa_admit(
        profile_id,
        binding["id"],
        authorization["id"],
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

    initial_path_reuse = _execute_initial(
        profile_id,
        authorization["id"],
        actor_id,
        key="phase-aa-illegal-x-reuse",
    )
    assert initial_path_reuse.status_code == 409, initial_path_reuse.text


def test_phase_aa_cross_tenant_and_stale_authorization_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, initial_execution, binding = _bound_v1(
        monkeypatch,
        "isolation",
    )
    authorization, _v_adapter = _later_authorization(
        profile_id=profile_id,
        claim_id=claim_id,
        actor_id=actor_id,
        suffix="isolation",
    )
    _enable_clean_aa(monkeypatch)

    _other_org, other_admin, _other_approver = _seed_tenant(
        "phase-aa-cross-tenant"
    )
    rejected = _aa_admit(
        profile_id,
        binding["id"],
        authorization["id"],
        other_admin,
        key="phase-aa-cross-tenant",
    )
    assert rejected.status_code == 404, rejected.text

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceFamilyVersionAdmissionExecution).count() == 0
        current = db.get(Document, UUID(initial_execution["document_id"]))
        assert current is not None
        current.created_at = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
        db.commit()

    stale = _aa_admit(
        profile_id,
        binding["id"],
        authorization["id"],
        actor_id,
        key="phase-aa-stale-auth",
    )
    assert stale.status_code == 409, stale.text

    with TestingSessionLocal() as db:
        current = db.get(Document, UUID(initial_execution["document_id"]))
        assert current is not None
        assert current.is_current is True
        assert current.version_number == 1
        assert db.query(ExternalDocumentSourceFamilyVersionAdmissionExecution).count() == 0

def test_phase_aa_rejects_same_content_even_when_remote_metadata_version_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "same-content",
    )
    authorization, _v_adapter = _later_authorization(
        profile_id=profile_id,
        claim_id=claim_id,
        actor_id=actor_id,
        suffix="same-content",
        body=_T_BODY,
        version="f" * 64,
        modified=datetime(2026, 9, 19, 16, 30, tzinfo=UTC),
    )
    _enable_clean_aa(monkeypatch)

    rejected = _aa_admit(
        profile_id,
        binding["id"],
        authorization["id"],
        actor_id,
        key="phase-aa-same-content",
    )
    assert rejected.status_code == 409, rejected.text
    assert "duplicate" in rejected.text.lower() or "bytes" in rejected.text.lower()

    with TestingSessionLocal() as db:
        rows = list(
            db.scalars(
                select(Document).where(
                    Document.claim_id == claim_id,
                    Document.document_family_id
                    == UUID(binding["document_family_id"]),
                    Document.deleted_at.is_(None),
                )
            ).all()
        )
        assert len(rows) == 1
        assert rows[0].version_number == 1
        assert rows[0].is_current is True


def test_phase_aa_rejects_authorization_for_a_different_claim_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "wrong-family",
    )
    authorization, _v_adapter = _later_authorization(
        profile_id=profile_id,
        claim_id=claim_id,
        actor_id=actor_id,
        suffix="wrong-family",
    )

    with TestingSessionLocal() as db:
        latest_v = db.scalar(
            select(ExternalDocumentSourceGeneration3ChangeDetectionExecution)
            .where(
                ExternalDocumentSourceGeneration3ChangeDetectionExecution.profile_id
                == UUID(profile_id),
                ExternalDocumentSourceGeneration3ChangeDetectionExecution.status
                == "completed",
                ExternalDocumentSourceGeneration3ChangeDetectionExecution.result_status
                == "unchanged",
            )
            .order_by(
                ExternalDocumentSourceGeneration3ChangeDetectionExecution.created_at.desc(),
                ExternalDocumentSourceGeneration3ChangeDetectionExecution.id.desc(),
            )
            .limit(1)
        )
        assert latest_v is not None
        latest_v_id = latest_v.id

    other_claim_id = _seed_claim(actor_id, "aa-wrong-family-other")
    other_authorization = _authorize(
        profile_id,
        str(latest_v_id),
        other_claim_id,
        actor_id,
        key="phase-aa-wrong-family-other-auth",
    )
    assert other_authorization.status_code == 201, other_authorization.text

    rejected = _aa_admit(
        profile_id,
        binding["id"],
        other_authorization.json()["id"],
        actor_id,
        key="phase-aa-wrong-family-exec",
    )
    assert rejected.status_code == 409, rejected.text

    with TestingSessionLocal() as db:
        assert (
            db.query(ExternalDocumentSourceFamilyVersionAdmissionExecution)
            .filter(
                ExternalDocumentSourceFamilyVersionAdmissionExecution.binding_id
                == UUID(binding["id"])
            )
            .count()
            == 0
        )
        current = list(
            db.scalars(
                select(Document).where(
                    Document.claim_id == claim_id,
                    Document.document_family_id
                    == UUID(binding["document_family_id"]),
                    Document.is_current.is_(True),
                )
            ).all()
        )
        assert len(current) == 1
        assert current[0].version_number == 1

    # Ensure the valid authorization created for the original Claim was not
    # accidentally consumed by the wrong-family attempt.
    _enable_clean_aa(monkeypatch)
    accepted = _aa_admit(
        profile_id,
        binding["id"],
        authorization["id"],
        actor_id,
        key="phase-aa-correct-family-after-reject",
    )
    assert accepted.status_code == 201, accepted.text


def test_phase_aa_binding_tamper_fails_before_document_version_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "tamper",
    )
    authorization, _v_adapter = _later_authorization(
        profile_id=profile_id,
        claim_id=claim_id,
        actor_id=actor_id,
        suffix="tamper",
    )
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
        authorization["id"],
        actor_id,
        key="phase-aa-tampered-binding",
    )
    assert rejected.status_code == 409, rejected.text

    with TestingSessionLocal() as db:
        documents = list(
            db.scalars(
                select(Document).where(
                    Document.claim_id == claim_id,
                    Document.document_family_id
                    == UUID(binding["document_family_id"]),
                    Document.deleted_at.is_(None),
                )
            ).all()
        )
        assert len(documents) == 1
        assert documents[0].version_number == 1
        assert documents[0].is_current is True
        assert db.query(ExternalDocumentSourceFamilyVersionAdmissionExecution).count() == 0


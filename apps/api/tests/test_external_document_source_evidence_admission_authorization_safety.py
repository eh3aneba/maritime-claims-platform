from uuid import UUID

from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.evidence_admission_authorization_models import (
    ExternalDocumentSourceEvidenceAdmissionAuthorization,
    ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import _ChangeAdapter
from tests.test_external_document_source_discovery import _headers
from tests.test_external_document_source_evidence_admission_authorization import (
    _authorize,
    _seed_claim,
    setup_function as _phase_w_setup,
    teardown_function as _phase_w_teardown,
)
from tests.test_external_document_source_generation_3_change_detection import (
    _baseline_projection,
    _completed_phase_u,
    _observe,
)


def setup_function() -> None:
    _phase_w_setup()


def teardown_function() -> None:
    _phase_w_teardown()


def _completed_authorization():
    upstream = _completed_phase_u()
    requester_id = upstream[0]
    profile_id = upstream[1]
    u_body = upstream[9]
    adapter = _ChangeAdapter()
    adapter.result = ExactItemMetadataResult(found=True, item=_baseline_projection())
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", adapter,
    )
    observed = _observe(profile_id, u_body["id"], requester_id, key="phase-w-safety-v")
    assert observed.status_code == 201, observed.text
    claim_id = _seed_claim(requester_id, "safety")
    authorized = _authorize(
        profile_id,
        observed.json()["id"],
        claim_id,
        requester_id,
        key="phase-w-safety-auth",
    )
    assert authorized.status_code == 201, authorized.text
    return requester_id, profile_id, adapter, authorized.json()


def test_phase_w_authorization_tamper_fails_closed_without_provider_call() -> None:
    requester_id, profile_id, adapter, body = _completed_authorization()
    calls_before = adapter.calls
    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceEvidenceAdmissionAuthorization, UUID(body["id"]))
        assert row is not None
        row.authorization_hash = "a" * 64
        db.commit()

    fetched = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/evidence-admission-authorizations/{body['id']}",
        headers=_headers(requester_id),
    )
    assert fetched.status_code == 409, fetched.text
    assert adapter.calls == calls_before


def test_phase_w_receipt_tamper_fails_closed_without_provider_call() -> None:
    requester_id, profile_id, adapter, body = _completed_authorization()
    calls_before = adapter.calls
    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt)
            .filter(
                ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt.authorization_id
                == UUID(body["id"])
            )
            .one()
        )
        receipt.decision_hash = "b" * 64
        db.commit()

    fetched = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/evidence-admission-authorizations/{body['id']}",
        headers=_headers(requester_id),
    )
    assert fetched.status_code == 409, fetched.text
    assert adapter.calls == calls_before

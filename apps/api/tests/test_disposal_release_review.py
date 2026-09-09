import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.service import create_auth_session
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.claims.retention_disposal_quarantine_models import DisposalQuarantineStage
from app.modules.claims.retention_disposal_release_models import DisposalReleaseReview
from app.modules.claims.retention_disposal_release_service import (
    RELEASE_MINIMUM_QUARANTINE_DWELL,
)
from app.modules.claims.retention_service import create_retention_policy
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_tenant(
    *,
    slug: str,
    claim_age_days: int = 120,
) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Release {slug}", slug=slug)
        db.add(org)
        db.flush()
        requester = User(
            organization_id=org.id,
            email=f"requester-{slug}@example.com",
            full_name=f"Requester {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        stage_creator = User(
            organization_id=org.id,
            email=f"stage-{slug}@example.com",
            full_name=f"Stage Creator {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        final_approver = User(
            organization_id=org.id,
            email=f"final-{slug}@example.com",
            full_name=f"Final Approver {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        manager = User(
            organization_id=org.id,
            email=f"manager-{slug}@example.com",
            full_name=f"Manager {slug}",
            password_hash="local",
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        vessel = Vessel(organization_id=org.id, name=f"MT {slug.upper()}")
        db.add_all([requester, stage_creator, final_approver, manager, vessel])
        db.flush()
        anchor = datetime.now(timezone.utc) - timedelta(days=claim_age_days)
        claim = Claim(
            organization_id=org.id,
            vessel_id=vessel.id,
            handler_id=manager.id,
            claim_reference=f"REL-{slug.upper()}-001",
            status=ClaimStatus.CLOSED,
            incident_date=date(2026, 1, 1),
            notification_date=date(2026, 1, 2),
            incident_description="Closed claim for final release review governance tests.",
            currency="USD",
            created_at=anchor,
            updated_at=anchor,
        )
        db.add(claim)
        db.flush()
        create_retention_policy(
            db,
            organization_id=org.id,
            closed_claim_retention_days=30,
            evidence_retention_days=30,
            enabled=True,
            disposal_enabled=True,
            created_by_id=requester.id,
        )
        db.commit()
        return (
            org.id,
            requester.id,
            stage_creator.id,
            final_approver.id,
            manager.id,
            claim.id,
        )


def _headers(user_id: UUID) -> dict[str, str]:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        session = create_auth_session(db, user=user)
        db.commit()
        token = create_access_token(
            user_id=user.id,
            organization_id=user.organization_id,
            role=user.role.value,
            session_id=session.id,
            identity_source=session.identity_source,
            auth_method=session.auth_method,
        )
    return {"Authorization": f"Bearer {token}"}


def _add_document(
    *,
    organization_id: UUID,
    claim_id: UUID,
    uploaded_by_id: UUID,
    storage_key: str,
    age_days: int = 90,
    file_hash: str = "e" * 64,
) -> UUID:
    with TestingSessionLocal() as db:
        anchor = datetime.now(timezone.utc) - timedelta(days=age_days)
        document = Document(
            organization_id=organization_id,
            claim_id=claim_id,
            uploaded_by_id=uploaded_by_id,
            filename="survey.pdf",
            original_filename="survey.pdf",
            mime_type="application/pdf",
            file_size_bytes=16384,
            file_hash=file_hash,
            storage_key=storage_key,
            processing_status=DocumentProcessingStatus.PROCESSED,
            created_at=anchor,
            updated_at=anchor,
        )
        db.add(document)
        db.commit()
        return document.id


def _chain_to_stage(
    claim_id: UUID,
    requester_id: UUID,
    stage_creator_id: UUID,
) -> tuple[str, dict[str, str], dict[str, str]]:
    requester_headers = _headers(requester_id)
    stage_headers = _headers(stage_creator_id)
    requested = client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations",
        headers=requester_headers,
        json={"reason": "Retention window expired and requires governed disposal review."},
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]
    approved = client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations/{authorization_id}/approve",
        headers=stage_headers,
        json={"reason": "Independent Admin confirms the exact retention snapshot."},
    )
    assert approved.status_code == 200, approved.text
    manifest = client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations/{authorization_id}/execution-manifest",
        headers=stage_headers,
    )
    assert manifest.status_code == 201, manifest.text
    manifest_id = manifest.json()["id"]
    ceremony = client.post(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests/{manifest_id}/dry-run-ceremony",
        headers=requester_headers,
        json={"reason": "Open the non-destructive rehearsal before final release governance."},
    )
    assert ceremony.status_code == 201, ceremony.text
    ceremony_id = ceremony.json()["id"]
    attested = client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/attest",
        headers=stage_headers,
        json={"reason": "Independent Admin attests the exact non-destructive rehearsal."},
    )
    assert attested.status_code == 200, attested.text
    stage = client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/quarantine-stage",
        headers=stage_headers,
        json={"reason": "Create the reversible logical quarantine overlay before release review."},
    )
    assert stage.status_code == 201, stage.text
    assert stage.json()["status"] == "staged"
    return stage.json()["id"], requester_headers, stage_headers


def _stage_time(stage_id: str) -> datetime:
    with TestingSessionLocal() as db:
        stage = db.get(DisposalQuarantineStage, UUID(stage_id))
        assert stage is not None
        value = stage.staged_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _set_release_clock(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr(
        "app.modules.claims.retention_disposal_release_service._utc_now",
        lambda: value,
    )


def _request_release(
    claim_id: UUID,
    stage_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/disposal-quarantine-stages/{stage_id}/release-review",
        headers=headers,
        json={"reason": "Request independent final review of the exact live quarantine lineage."},
    )


def test_minimum_quarantine_dwell_is_enforced(monkeypatch) -> None:
    _org, requester_id, stage_creator_id, _final_id, _manager_id, claim_id = _seed_tenant(
        slug="dwell"
    )
    stage_id, requester_headers, _stage_headers = _chain_to_stage(
        claim_id, requester_id, stage_creator_id
    )
    staged_at = _stage_time(stage_id)
    _set_release_clock(
        monkeypatch,
        staged_at + RELEASE_MINIMUM_QUARANTINE_DWELL - timedelta(seconds=1),
    )

    blocked = _request_release(claim_id, stage_id, requester_headers)
    assert blocked.status_code == 409, blocked.text
    detail = blocked.json()["detail"]
    assert detail["code"] == "disposal_release_review_preflight_failed"
    assert detail["outcome"] == "blocked"
    assert "minimum_quarantine_dwell_not_met" in detail["blocking_reasons"]

    with TestingSessionLocal() as db:
        assert db.query(DisposalReleaseReview).filter(
            DisposalReleaseReview.claim_id == claim_id
        ).count() == 0
        stage = db.get(DisposalQuarantineStage, UUID(stage_id))
        assert stage is not None and stage.status == "staged"


def test_release_approval_is_independent_hashed_and_non_destructive(monkeypatch) -> None:
    org_id, requester_id, stage_creator_id, final_id, manager_id, claim_id = _seed_tenant(
        slug="approve"
    )
    raw_key = f"private-bucket/{org_id}/{claim_id}/survey.pdf"
    document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=raw_key,
    )
    stage_id, requester_headers, stage_headers = _chain_to_stage(
        claim_id, requester_id, stage_creator_id
    )
    eligible = _stage_time(stage_id) + RELEASE_MINIMUM_QUARANTINE_DWELL + timedelta(seconds=1)
    _set_release_clock(monkeypatch, eligible)
    requested = _request_release(claim_id, stage_id, requester_headers)
    assert requested.status_code == 201, requested.text
    body = requested.json()
    assert body["status"] == "pending_final_approval"
    assert len(body["release_snapshot_hash"]) == 64
    assert len(body["review_hash"]) == 64
    assert body["approval_hash"] is None
    snapshot_text = json.dumps(body["release_snapshot"], sort_keys=True)
    assert raw_key not in snapshot_text
    assert "private-bucket" not in snapshot_text
    assert '"execution_authority_created": false' in snapshot_text.lower()
    assert '"destructive_action_performed": false' in snapshot_text.lower()

    _set_release_clock(monkeypatch, eligible + timedelta(seconds=10))
    requester_self = client.post(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{body['id']}/approve",
        headers=requester_headers,
        json={"reason": "Requester must not be able to self-approve final release."},
    )
    assert requester_self.status_code == 409
    assert "cannot approve" in requester_self.text.lower()

    stage_creator_self = client.post(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{body['id']}/approve",
        headers=stage_headers,
        json={"reason": "Stage creator must not be able to approve final release."},
    )
    assert stage_creator_self.status_code == 409
    assert "stage creator" in stage_creator_self.text.lower()

    final_headers = _headers(final_id)
    approved = client.post(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{body['id']}/approve",
        headers=final_headers,
        json={"reason": "Independent final Admin confirms the exact live release snapshot."},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "approved"
    assert approved_body["approved_by_id"] == str(final_id)
    assert len(approved_body["approval_hash"]) == 64

    manager_get = client.get(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{body['id']}",
        headers=_headers(manager_id),
    )
    assert manager_get.status_code == 200

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        document = db.get(Document, document_id)
        stage = db.get(DisposalQuarantineStage, UUID(stage_id))
        review = db.get(DisposalReleaseReview, UUID(body["id"]))
        assert claim is not None and claim.deleted_at is None
        assert document is not None and document.deleted_at is None
        assert document.storage_key == raw_key
        assert stage is not None and stage.status == "staged"
        assert review is not None and review.status == "approved"
        audit_text = json.dumps(
            [
                row.new_values
                for row in db.query(AuditLog)
                .filter(AuditLog.organization_id == org_id)
                .all()
            ],
            sort_keys=True,
        ).lower()
        assert raw_key.lower() not in audit_text
        assert '"execution_authority_created": false' in audit_text
        assert '"physical_quarantine_performed": false' in audit_text
        assert '"destructive_action_performed": false' in audit_text


def test_new_legal_hold_after_request_invalidates_final_review(monkeypatch) -> None:
    org_id, requester_id, stage_creator_id, final_id, _manager_id, claim_id = _seed_tenant(
        slug="hold"
    )
    raw_key = f"bucket/{org_id}/{claim_id}/survey.pdf"
    document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=raw_key,
    )
    stage_id, requester_headers, _stage_headers = _chain_to_stage(
        claim_id, requester_id, stage_creator_id
    )
    eligible = _stage_time(stage_id) + RELEASE_MINIMUM_QUARANTINE_DWELL + timedelta(seconds=1)
    _set_release_clock(monkeypatch, eligible)
    requested = _request_release(claim_id, stage_id, requester_headers)
    assert requested.status_code == 201
    review_id = requested.json()["id"]

    hold = client.post(
        f"/api/v1/claims/{claim_id}/legal-holds",
        headers=requester_headers,
        json={
            "source": "litigation",
            "reason": "Counsel issued a preservation instruction before final release approval.",
        },
    )
    assert hold.status_code == 201, hold.text

    _set_release_clock(monkeypatch, eligible + timedelta(seconds=20))
    approval = client.post(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{review_id}/approve",
        headers=_headers(final_id),
        json={"reason": "Final reviewer performs mandatory fresh preservation revalidation."},
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["status"] == "invalidated"

    with TestingSessionLocal() as db:
        stage = db.get(DisposalQuarantineStage, UUID(stage_id))
        review = db.get(DisposalReleaseReview, UUID(review_id))
        document = db.get(Document, document_id)
        assert stage is not None and stage.status == "invalidated"
        assert review is not None and review.status == "invalidated"
        assert document is not None and document.deleted_at is None
        assert document.storage_key == raw_key


def test_evidence_drift_after_request_invalidates_release_snapshot(monkeypatch) -> None:
    org_id, requester_id, stage_creator_id, final_id, _manager_id, claim_id = _seed_tenant(
        slug="drift"
    )
    original_key = f"bucket/{org_id}/{claim_id}/original.pdf"
    original_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=original_key,
    )
    stage_id, requester_headers, _stage_headers = _chain_to_stage(
        claim_id, requester_id, stage_creator_id
    )
    eligible = _stage_time(stage_id) + RELEASE_MINIMUM_QUARANTINE_DWELL + timedelta(seconds=1)
    _set_release_clock(monkeypatch, eligible)
    requested = _request_release(claim_id, stage_id, requester_headers)
    assert requested.status_code == 201
    review_id = requested.json()["id"]

    new_key = f"bucket/{org_id}/{claim_id}/new.pdf"
    new_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=new_key,
        file_hash="f" * 64,
    )

    _set_release_clock(monkeypatch, eligible + timedelta(seconds=20))
    approval = client.post(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{review_id}/approve",
        headers=_headers(final_id),
        json={"reason": "Final reviewer must fail closed when evidence lineage changes."},
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "invalidated"

    with TestingSessionLocal() as db:
        original = db.get(Document, original_id)
        new = db.get(Document, new_id)
        assert original is not None and original.deleted_at is None
        assert new is not None and new.deleted_at is None
        assert original.storage_key == original_key
        assert new.storage_key == new_key


def test_review_expiry_rejection_and_cancellation_are_terminal(monkeypatch) -> None:
    _org, requester_id, stage_creator_id, final_id, _manager_id, claim_id = _seed_tenant(
        slug="terminal"
    )
    stage_id, requester_headers, _stage_headers = _chain_to_stage(
        claim_id, requester_id, stage_creator_id
    )
    eligible = _stage_time(stage_id) + RELEASE_MINIMUM_QUARANTINE_DWELL + timedelta(seconds=1)
    _set_release_clock(monkeypatch, eligible)
    first = _request_release(claim_id, stage_id, requester_headers)
    assert first.status_code == 201
    first_id = first.json()["id"]

    rejected = client.post(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{first_id}/reject",
        headers=_headers(final_id),
        json={"reason": "Final reviewer rejects the release and preserves the governance chain."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    unchanged = client.post(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{first_id}/approve",
        headers=_headers(final_id),
        json={"reason": "A rejected review must not be revived by later approval."},
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["status"] == "rejected"

    duplicate = _request_release(claim_id, stage_id, requester_headers)
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.text.lower()


def test_stored_snapshot_tampering_invalidates_approval(monkeypatch) -> None:
    _org, requester_id, stage_creator_id, final_id, _manager_id, claim_id = _seed_tenant(
        slug="tamper"
    )
    stage_id, requester_headers, _stage_headers = _chain_to_stage(
        claim_id, requester_id, stage_creator_id
    )
    eligible = _stage_time(stage_id) + RELEASE_MINIMUM_QUARANTINE_DWELL + timedelta(seconds=1)
    _set_release_clock(monkeypatch, eligible)
    requested = _request_release(claim_id, stage_id, requester_headers)
    assert requested.status_code == 201
    review_id = UUID(requested.json()["id"])

    with TestingSessionLocal() as db:
        review = db.get(DisposalReleaseReview, review_id)
        assert review is not None
        snapshot = dict(review.release_snapshot)
        snapshot["document_count"] = 999
        review.release_snapshot = snapshot
        db.commit()

    _set_release_clock(monkeypatch, eligible + timedelta(seconds=20))
    approval = client.post(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{review_id}/approve",
        headers=_headers(final_id),
        json={"reason": "Final reviewer detects stored release snapshot integrity failure."},
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "invalidated"
    assert "integrity" in (approval.json()["terminal_reason"] or "").lower()


def test_reader_cross_tenant_and_mfa_fail_closed(monkeypatch) -> None:
    org_id, requester_id, stage_creator_id, _final_id, manager_id, claim_id = _seed_tenant(
        slug="rbac"
    )
    _other_org, other_admin, _other_stage, _other_final, _other_manager, _other_claim = _seed_tenant(
        slug="other"
    )
    stage_id, requester_headers, _stage_headers = _chain_to_stage(
        claim_id, requester_id, stage_creator_id
    )
    eligible = _stage_time(stage_id) + RELEASE_MINIMUM_QUARANTINE_DWELL + timedelta(seconds=1)
    _set_release_clock(monkeypatch, eligible)
    requested = _request_release(claim_id, stage_id, requester_headers)
    assert requested.status_code == 201
    review_id = requested.json()["id"]

    manager_headers = _headers(manager_id)
    manager_get = client.get(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{review_id}",
        headers=manager_headers,
    )
    assert manager_get.status_code == 200
    manager_mutation = client.post(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{review_id}/cancel",
        headers=manager_headers,
        json={"reason": "Claims Manager must remain read-only for final release governance."},
    )
    assert manager_mutation.status_code == 403

    cross_tenant = client.get(
        f"/api/v1/claims/{claim_id}/disposal-release-reviews/{review_id}",
        headers=_headers(other_admin),
    )
    assert cross_tenant.status_code == 404

    org2, requester2, stage2, _final2, _manager2, claim2 = _seed_tenant(slug="mfa")
    stage_id2, requester_headers2, _stage_headers2 = _chain_to_stage(
        claim2, requester2, stage2
    )
    with TestingSessionLocal() as db:
        db.add(
            MfaPolicy(
                organization_id=org2,
                is_enabled=True,
                required_roles=[UserRole.ADMIN.value],
                updated_by_id=requester2,
            )
        )
        db.commit()
    eligible2 = _stage_time(stage_id2) + RELEASE_MINIMUM_QUARANTINE_DWELL + timedelta(seconds=1)
    _set_release_clock(monkeypatch, eligible2)
    blocked_mfa = _request_release(claim2, stage_id2, requester_headers2)
    assert blocked_mfa.status_code == 403
    assert blocked_mfa.json()["detail"]["code"] == "mfa_enrollment_required"

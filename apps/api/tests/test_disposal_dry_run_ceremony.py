import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.service import create_auth_session
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.claims.retention_disposal_dry_run_models import DisposalDryRunCeremony
from app.modules.claims.retention_disposal_dry_run_service import (
    attest_disposal_dry_run_ceremony,
    open_disposal_dry_run_ceremony,
)
from app.modules.claims.retention_disposal_manifest_models import DisposalExecutionManifest
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
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Dry Run {slug}", slug=slug)
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
        approver = User(
            organization_id=org.id,
            email=f"approver-{slug}@example.com",
            full_name=f"Approver {slug}",
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
        db.add_all([requester, approver, manager, vessel])
        db.flush()
        anchor = datetime.now(timezone.utc) - timedelta(days=claim_age_days)
        claim = Claim(
            organization_id=org.id,
            vessel_id=vessel.id,
            handler_id=manager.id,
            claim_reference=f"DRY-{slug.upper()}-001",
            status=ClaimStatus.CLOSED,
            incident_date=date(2026, 1, 1),
            notification_date=date(2026, 1, 2),
            incident_description="Closed claim for dry-run ceremony governance tests.",
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
        return org.id, requester.id, approver.id, manager.id, claim.id


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


def _approved_manifest(
    claim_id: UUID,
    requester_id: UUID,
    approver_id: UUID,
) -> tuple[str, str, dict[str, str], dict[str, str]]:
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    requested = client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations",
        headers=requester_headers,
        json={"reason": "Retention window expired and requires governed disposal review."},
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]
    approved = client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations/{authorization_id}/approve",
        headers=approver_headers,
        json={"reason": "Independent Admin confirms the exact retention snapshot."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    manifest = client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations/{authorization_id}/execution-manifest",
        headers=approver_headers,
    )
    assert manifest.status_code == 201, manifest.text
    assert manifest.json()["status"] == "ready"
    return authorization_id, manifest.json()["id"], requester_headers, approver_headers


def _add_document(
    *,
    organization_id: UUID,
    claim_id: UUID,
    uploaded_by_id: UUID,
    storage_key: str,
    age_days: int = 90,
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
            file_size_bytes=4096,
            file_hash="b" * 64,
            storage_key=storage_key,
            processing_status=DocumentProcessingStatus.PROCESSED,
            created_at=anchor,
            updated_at=anchor,
        )
        db.add(document)
        db.commit()
        return document.id


def _open_ceremony(
    claim_id: UUID,
    manifest_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests/{manifest_id}/dry-run-ceremony",
        headers=headers,
        json={"reason": "Open a non-destructive rehearsal for independent human attestation."},
    )


def test_dry_run_plan_is_hashed_non_destructive_and_independently_attested() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="attest")
    raw_storage_key = f"private-bucket/{org_id}/{claim_id}/survey.pdf"
    document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=raw_storage_key,
    )
    _authorization_id, manifest_id, requester_headers, approver_headers = _approved_manifest(
        claim_id, requester_id, approver_id
    )

    opened = _open_ceremony(claim_id, manifest_id, requester_headers)
    assert opened.status_code == 201, opened.text
    body = opened.json()
    assert body["status"] == "pending_attestation"
    assert body["document_count"] == 1
    assert body["total_file_size_bytes"] == 4096
    assert len(body["plan_hash"]) == 64
    assert len(body["ceremony_hash"]) == 64
    assert body["attestation_hash"] is None

    rendered_plan = json.dumps(body["dry_run_plan"], sort_keys=True)
    assert raw_storage_key not in rendered_plan
    assert "private-bucket" not in rendered_plan
    assert "storage_key_fingerprint" in rendered_plan
    assert "dry_run_only" in rendered_plan
    assert "file_hash" in rendered_plan

    self_attest = client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{body['id']}/attest",
        headers=requester_headers,
        json={"reason": "Creator should not be permitted to self-attest this rehearsal."},
    )
    assert self_attest.status_code == 409
    assert "cannot attest" in self_attest.text.lower()

    attested = client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{body['id']}/attest",
        headers=approver_headers,
        json={"reason": "Independent Admin reproduced the exact dry-run plan and attests it."},
    )
    assert attested.status_code == 200, attested.text
    attested_body = attested.json()
    assert attested_body["status"] == "attested"
    assert attested_body["attested_by_id"] == str(approver_id)
    assert len(attested_body["attestation_hash"]) == 64
    assert "execution" not in {key.lower() for key in attested_body if key.endswith("token")}

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        document = db.get(Document, document_id)
        ceremony = db.get(DisposalDryRunCeremony, UUID(body["id"]))
        assert claim is not None and claim.deleted_at is None
        assert document is not None and document.deleted_at is None
        assert document.storage_key == raw_storage_key
        assert ceremony is not None and ceremony.status == "attested"
        audit_text = json.dumps(
            [
                row.new_values
                for row in db.query(AuditLog)
                .filter(AuditLog.organization_id == org_id)
                .all()
            ],
            sort_keys=True,
        ).lower()
        assert raw_storage_key.lower() not in audit_text
        assert '"destructive_action_performed": false' in audit_text
        assert '"execution_authority_created": false' in audit_text


def test_opening_ceremony_revalidates_manifest_and_preserves_blocked_state() -> None:
    _org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="hold")
    _authorization_id, manifest_id, requester_headers, _approver_headers = _approved_manifest(
        claim_id, requester_id, approver_id
    )
    hold = client.post(
        f"/api/v1/claims/{claim_id}/legal-holds",
        headers=requester_headers,
        json={
            "source": "litigation",
            "reason": "Counsel issued a preservation instruction before dry-run rehearsal.",
        },
    )
    assert hold.status_code == 201

    blocked = _open_ceremony(claim_id, manifest_id, requester_headers)
    assert blocked.status_code == 409, blocked.text
    detail = blocked.json()["detail"]
    assert detail["outcome"] == "blocked"
    assert "active_legal_hold" in " ".join(detail["blocking_reasons"])

    manifest = client.get(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests/{manifest_id}",
        headers=requester_headers,
    )
    assert manifest.status_code == 200
    assert manifest.json()["status"] == "blocked"


def test_attestation_fails_closed_when_storage_or_evidence_drifts() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="drift")
    document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=f"bucket/{org_id}/{claim_id}/before.pdf",
    )
    _authorization_id, manifest_id, requester_headers, approver_headers = _approved_manifest(
        claim_id, requester_id, approver_id
    )
    opened = _open_ceremony(claim_id, manifest_id, requester_headers)
    assert opened.status_code == 201, opened.text

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        document.storage_key = f"bucket/{org_id}/{claim_id}/after.pdf"
        db.commit()

    attested = client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{opened.json()['id']}/attest",
        headers=approver_headers,
        json={"reason": "Independent attester attempts a fresh live rehearsal after drift."},
    )
    assert attested.status_code == 200, attested.text
    assert attested.json()["status"] == "invalidated"

    manifest = client.get(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests/{manifest_id}",
        headers=requester_headers,
    )
    assert manifest.status_code == 200
    assert manifest.json()["status"] == "invalidated"

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        document = db.get(Document, document_id)
        assert claim is not None and claim.deleted_at is None
        assert document is not None and document.deleted_at is None


def test_ceremony_expiry_is_fail_closed_without_any_execution() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="expiry")
    _authorization_id, manifest_id, _requester_headers, _approver_headers = _approved_manifest(
        claim_id, requester_id, approver_id
    )
    base_time = datetime.now(timezone.utc)
    with TestingSessionLocal() as db:
        ceremony = open_disposal_dry_run_ceremony(
            db,
            organization_id=org_id,
            claim_id=claim_id,
            manifest_id=UUID(manifest_id),
            created_by_id=requester_id,
            opening_reason="Open a bounded dry-run ceremony for expiry testing.",
            now=base_time,
        )
        db.commit()
        ceremony_id = ceremony.id
        expiry = ceremony.ceremony_expires_at

    with TestingSessionLocal() as db:
        ceremony, outcome = attest_disposal_dry_run_ceremony(
            db,
            organization_id=org_id,
            claim_id=claim_id,
            ceremony_id=ceremony_id,
            attested_by_id=approver_id,
            attestation_reason="Attestation intentionally occurs after the bounded ceremony expiry.",
            now=expiry + timedelta(seconds=1),
        )
        db.commit()
        assert outcome == "expired"
        assert ceremony.status == "expired"
        assert ceremony.attestation_hash is None
        claim = db.get(Claim, claim_id)
        assert claim is not None and claim.deleted_at is None


def test_cancelled_ceremony_is_terminal_and_does_not_revive() -> None:
    _org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="cancel")
    _authorization_id, manifest_id, requester_headers, approver_headers = _approved_manifest(
        claim_id, requester_id, approver_id
    )
    opened = _open_ceremony(claim_id, manifest_id, requester_headers)
    assert opened.status_code == 201
    ceremony_id = opened.json()["id"]

    cancelled = client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/cancel",
        headers=requester_headers,
        json={"reason": "Operator cancels the rehearsal before independent attestation."},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    later_attest = client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/attest",
        headers=approver_headers,
        json={"reason": "A terminal cancelled ceremony must never revive through attestation."},
    )
    assert later_attest.status_code == 200
    assert later_attest.json()["status"] == "cancelled"
    assert later_attest.json()["attestation_hash"] is None


def test_stored_ceremony_plan_tampering_invalidates_attestation() -> None:
    _org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="tamper")
    _authorization_id, manifest_id, requester_headers, approver_headers = _approved_manifest(
        claim_id, requester_id, approver_id
    )
    opened = _open_ceremony(claim_id, manifest_id, requester_headers)
    assert opened.status_code == 201
    ceremony_id = UUID(opened.json()["id"])

    with TestingSessionLocal() as db:
        ceremony = db.get(DisposalDryRunCeremony, ceremony_id)
        assert ceremony is not None
        tampered = list(ceremony.dry_run_plan)
        tampered[0] = {**tampered[0], "simulated_action": "tampered_action"}
        ceremony.dry_run_plan = tampered
        db.commit()

    result = client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/attest",
        headers=approver_headers,
        json={"reason": "Independent attester verifies stored ceremony integrity before acceptance."},
    )
    assert result.status_code == 200
    assert result.json()["status"] == "invalidated"
    assert "integrity" in result.json()["terminal_reason"].lower()


def test_duplicate_ceremony_for_same_manifest_is_rejected() -> None:
    _org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="duplicate")
    _authorization_id, manifest_id, requester_headers, _approver_headers = _approved_manifest(
        claim_id, requester_id, approver_id
    )
    first = _open_ceremony(claim_id, manifest_id, requester_headers)
    assert first.status_code == 201
    second = _open_ceremony(claim_id, manifest_id, requester_headers)
    assert second.status_code == 409
    assert "already exists" in second.text.lower()


def test_reader_rbac_cross_tenant_and_mfa_fail_closed() -> None:
    org_id, requester_id, approver_id, manager_id, claim_id = _seed_tenant(slug="rbac")
    _other_org, other_admin_id, _other_approver, _other_manager, _other_claim = _seed_tenant(
        slug="other"
    )
    _authorization_id, manifest_id, requester_headers, _approver_headers = _approved_manifest(
        claim_id, requester_id, approver_id
    )
    opened = _open_ceremony(claim_id, manifest_id, requester_headers)
    assert opened.status_code == 201
    ceremony_id = opened.json()["id"]

    manager_headers = _headers(manager_id)
    manager_read = client.get(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies",
        headers=manager_headers,
    )
    assert manager_read.status_code == 200
    assert manager_read.json()[0]["id"] == ceremony_id

    manager_mutation = client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/cancel",
        headers=manager_headers,
        json={"reason": "Claims Manager has read access but must not mutate ceremony state."},
    )
    assert manager_mutation.status_code == 403

    cross_tenant = client.get(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}",
        headers=_headers(other_admin_id),
    )
    assert cross_tenant.status_code == 404

    org2, requester2, approver2, _manager2, claim2 = _seed_tenant(slug="mfa")
    _auth2, manifest2, requester2_headers, _approver2_headers = _approved_manifest(
        claim2, requester2, approver2
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

    blocked_mfa = _open_ceremony(claim2, manifest2, requester2_headers)
    assert blocked_mfa.status_code == 403
    detail = blocked_mfa.json()["detail"]
    assert detail["code"] == "mfa_enrollment_required"


def test_attested_ceremony_does_not_mutate_manifest_or_claim_content() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="immutable")
    _authorization_id, manifest_id, requester_headers, approver_headers = _approved_manifest(
        claim_id, requester_id, approver_id
    )
    opened = _open_ceremony(claim_id, manifest_id, requester_headers)
    assert opened.status_code == 201
    attested = client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{opened.json()['id']}/attest",
        headers=approver_headers,
        json={"reason": "Attestation confirms rehearsal only and creates no execution authority."},
    )
    assert attested.status_code == 200
    assert attested.json()["status"] == "attested"

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        manifest = db.get(DisposalExecutionManifest, UUID(manifest_id))
        assert claim is not None and claim.deleted_at is None
        assert manifest is not None and manifest.status == "ready"
        assert manifest.terminal_at is None
        ceremony = db.get(DisposalDryRunCeremony, UUID(opened.json()["id"]))
        assert ceremony is not None
        assert ceremony.status == "attested"
        assert ceremony.terminal_at is None
        actions = {
            row.action
            for row in db.query(AuditLog)
            .filter(AuditLog.organization_id == org_id)
            .all()
        }
        assert "DISPOSAL_DRY_RUN_CEREMONY_ATTESTED" in actions

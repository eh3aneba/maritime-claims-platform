from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.core.security import create_access_token
from app.modules.auth.models import TotpMfaFactor
from app.modules.auth.service import create_auth_session
from app.modules.documents.models import Document
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
    ExternalDocumentSourceRecurringObservationScheduleReceipt,
)
from app.modules.processing.models import DocumentProcessingJob
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_family_version_admission import _bound_v1

_REASON = (
    "Authorize bounded recurring metadata-only observation for this exact "
    "external Evidence family without granting downstream processing authority."
)
_REPLACE_REASON = (
    "Replace the recurring observation cadence through a new immutable schedule "
    "revision while preserving the prior authorization history."
)
_DISABLE_REASON = (
    "Disable recurring observation authority for this Evidence family and stop "
    "any future due authority from this schedule revision."
)


def setup_function() -> None:
    _phase_y_setup()


def teardown_function() -> None:
    _phase_y_teardown()


def _mfa_headers(user_id: UUID) -> dict[str, str]:
    now = datetime.now(UTC)
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        factor = (
            db.query(TotpMfaFactor)
            .filter(
                TotpMfaFactor.organization_id == user.organization_id,
                TotpMfaFactor.user_id == user.id,
                TotpMfaFactor.revoked_at.is_(None),
            )
            .one_or_none()
        )
        if factor is None:
            factor = TotpMfaFactor(
                organization_id=user.organization_id,
                user_id=user.id,
                issuer="MCRI Test",
                account_label=user.email,
                algorithm="SHA1",
                digits=6,
                period_seconds=30,
                secret_ciphertext="test-only-ciphertext",
                secret_nonce="test-only-nonce",
                secret_fingerprint=("a" * 64),
                confirmed_at=now,
            )
            db.add(factor)
            db.flush()
        else:
            factor.confirmed_at = factor.confirmed_at or now

        session = create_auth_session(db, user=user)
        session.mfa_verified_at = now
        session.mfa_method = "totp"
        session.mfa_factor_id = factor.id
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


def _authorize(
    profile_id: str,
    binding_id: str,
    actor_id: UUID,
    *,
    key: str,
    cadence: str = "hourly",
    reason: str = _REASON,
    effective_at: str | None = None,
    extra: dict | None = None,
    headers: dict[str, str] | None = None,
):
    payload = {
        "request_key": key,
        "reason": reason,
        "cadence_class": cadence,
    }
    if effective_at is not None:
        payload["effective_at"] = effective_at
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/evidence-family-bindings/{binding_id}"
            "/recurring-observation-schedules"
        ),
        headers=headers or _headers(actor_id),
        json=payload,
    )


def _replace(
    profile_id: str,
    schedule_id: str,
    actor_id: UUID,
    *,
    key: str,
    cadence: str,
    reason: str = _REPLACE_REASON,
    headers: dict[str, str] | None = None,
):
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/recurring-observation-schedules/{schedule_id}/replace"
        ),
        headers=headers or _headers(actor_id),
        json={
            "request_key": key,
            "reason": reason,
            "cadence_class": cadence,
        },
    )


def _disable(
    profile_id: str,
    schedule_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _DISABLE_REASON,
    headers: dict[str, str] | None = None,
):
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/recurring-observation-schedules/{schedule_id}/disable"
        ),
        headers=headers or _headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def test_phase_ab_authorize_replace_disable_is_authority_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, initial_execution, binding = _bound_v1(
        monkeypatch,
        "ab-lifecycle",
    )
    document_id = UUID(initial_execution["document_id"])
    mfa_headers = _mfa_headers(actor_id)

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        before = {
            "is_current": document.is_current,
            "version_number": document.version_number,
            "file_hash": document.file_hash,
            "processing_status": document.processing_status,
        }
        jobs_before = db.query(DocumentProcessingJob).count()

    forbidden = _authorize(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ab-forbidden",
        extra={
            "provider_io_authorized": True,
            "ai_authorized": True,
            "cron": "*/5 * * * *",
        },
        headers=mfa_headers,
    )
    assert forbidden.status_code == 422, forbidden.text

    authorized = _authorize(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ab-authorize-1",
        cadence="hourly",
        effective_at="2026-09-21T00:00:00Z",
        headers=mfa_headers,
    )
    assert authorized.status_code == 201, authorized.text
    first = authorized.json()
    assert first["status"] == "active"
    assert first["revision_number"] == 1
    assert first["prior_schedule_id"] is None
    assert first["cadence_class"] == "hourly"
    assert first["cadence_minutes"] == 60
    assert first["effective_at"] == "2026-09-21T00:00:00+00:00"
    assert first["next_due_at"] == first["effective_at"]
    assert first["active_binding_guard"] == binding["id"]

    for field in (
        "provider_client_constructed",
        "token_acquired",
        "remote_metadata_read_performed",
        "remote_content_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "document_mutated",
        "processing_enqueued",
        "ai_executed",
        "claim_mutated",
        "checkpoint_advanced",
        "background_worker_started",
    ):
        assert first[field] is False

    replay = _authorize(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ab-authorize-1",
        cadence="hourly",
        effective_at="2026-09-21T00:00:00Z",
        headers=mfa_headers,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first["id"]

    altered = _authorize(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ab-authorize-1",
        cadence="daily",
        effective_at="2026-09-21T00:00:00Z",
        headers=mfa_headers,
    )
    assert altered.status_code == 409, altered.text

    duplicate_active = _authorize(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ab-authorize-duplicate",
        cadence="every_6_hours",
        headers=mfa_headers,
    )
    assert duplicate_active.status_code == 409, duplicate_active.text

    active = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/evidence-family-bindings/{binding['id']}"
            "/recurring-observation-schedules/active"
        ),
        headers=mfa_headers,
    )
    assert active.status_code == 200, active.text
    assert active.json()["id"] == first["id"]

    replacement = _replace(
        profile_id,
        first["id"],
        actor_id,
        key="phase-ab-replace-2",
        cadence="every_6_hours",
        headers=mfa_headers,
    )
    assert replacement.status_code == 201, replacement.text
    second = replacement.json()
    assert second["status"] == "active"
    assert second["revision_number"] == 2
    assert second["prior_schedule_id"] == first["id"]
    assert second["cadence_minutes"] == 360

    replacement_replay = _replace(
        profile_id,
        first["id"],
        actor_id,
        key="phase-ab-replace-2",
        cadence="every_6_hours",
        headers=mfa_headers,
    )
    assert replacement_replay.status_code == 201, replacement_replay.text
    assert replacement_replay.json()["id"] == second["id"]

    wrong_action_replay = _disable(
        profile_id,
        first["id"],
        actor_id,
        key="phase-ab-replace-2",
        reason=_REPLACE_REASON,
        headers=mfa_headers,
    )
    assert wrong_action_replay.status_code == 409, wrong_action_replay.text

    disabled = _disable(
        profile_id,
        second["id"],
        actor_id,
        key="phase-ab-disable-2",
        headers=mfa_headers,
    )
    assert disabled.status_code == 200, disabled.text
    terminal = disabled.json()
    assert terminal["status"] == "disabled"
    assert terminal["active_binding_guard"] is None
    assert terminal["terminal_hash"] is not None

    disable_replay = _disable(
        profile_id,
        second["id"],
        actor_id,
        key="phase-ab-disable-2",
        headers=mfa_headers,
    )
    assert disable_replay.status_code == 200, disable_replay.text
    assert disable_replay.json()["id"] == second["id"]

    no_active = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/evidence-family-bindings/{binding['id']}"
            "/recurring-observation-schedules/active"
        ),
        headers=mfa_headers,
    )
    assert no_active.status_code == 200, no_active.text
    assert no_active.json() is None

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        assert document.claim_id == claim_id
        assert document.is_current == before["is_current"]
        assert document.version_number == before["version_number"]
        assert document.file_hash == before["file_hash"]
        assert document.processing_status == before["processing_status"]
        assert db.query(DocumentProcessingJob).count() == jobs_before

        rows = (
            db.query(ExternalDocumentSourceRecurringObservationSchedule)
            .order_by(
                ExternalDocumentSourceRecurringObservationSchedule.revision_number.asc()
            )
            .all()
        )
        assert len(rows) == 2
        assert rows[0].status == "disabled"
        assert rows[1].status == "disabled"
        assert (
            db.query(ExternalDocumentSourceRecurringObservationSchedule)
            .filter(
                ExternalDocumentSourceRecurringObservationSchedule.binding_id
                == UUID(binding["id"]),
                ExternalDocumentSourceRecurringObservationSchedule.status == "active",
            )
            .count()
            == 0
        )
        receipts = db.query(
            ExternalDocumentSourceRecurringObservationScheduleReceipt
        ).all()
        assert len(receipts) == 4


def test_phase_ab_rejects_unsupported_cadence_cross_tenant_and_non_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ab-gates",
    )
    mfa_headers = _mfa_headers(actor_id)

    unsupported = client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/evidence-family-bindings/{binding['id']}"
            "/recurring-observation-schedules"
        ),
        headers=mfa_headers,
        json={
            "request_key": "phase-ab-too-fast",
            "reason": _REASON,
            "cadence_class": "every_5_minutes",
        },
    )
    assert unsupported.status_code == 422, unsupported.text

    _other_org, other_admin, _other_approver = _seed_tenant("ab-other")
    other_mfa_headers = _mfa_headers(other_admin)
    cross_tenant = _authorize(
        profile_id,
        binding["id"],
        other_admin,
        key="phase-ab-cross-tenant",
        headers=other_mfa_headers,
    )
    assert cross_tenant.status_code == 404, cross_tenant.text

    with TestingSessionLocal() as db:
        admin = db.get(User, actor_id)
        assert admin is not None
        handler = User(
            organization_id=admin.organization_id,
            email="phase-ab-handler@example.com",
            full_name="Phase AB Handler",
            password_hash="local",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add(handler)
        db.commit()
        handler_id = handler.id

    non_admin = _authorize(
        profile_id,
        binding["id"],
        handler_id,
        key="phase-ab-non-admin",
    )
    assert non_admin.status_code == 403, non_admin.text


def test_phase_ab_requires_current_mfa_even_without_tenant_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ab-mfa",
    )
    denied = _authorize(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ab-mfa-required",
    )
    assert denied.status_code == 403, denied.text
    assert "mfa" in denied.text.lower()


def test_phase_ab_binding_tamper_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ab-tamper",
    )
    mfa_headers = _mfa_headers(actor_id)
    authorized = _authorize(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ab-tamper-auth",
        headers=mfa_headers,
    )
    assert authorized.status_code == 201, authorized.text

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceEvidenceFamilyBinding,
            UUID(binding["id"]),
        )
        assert row is not None
        row.stable_source_item_hash = "0" * 64
        db.commit()

    read = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/recurring-observation-schedules/{authorized.json()['id']}"
        ),
        headers=mfa_headers,
    )
    assert read.status_code == 409, read.text


def test_phase_ab_can_reauthorize_after_terminal_disable_as_next_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ab-reauthorize",
    )
    mfa_headers = _mfa_headers(actor_id)
    first = _authorize(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ab-reauth-1",
        headers=mfa_headers,
    )
    assert first.status_code == 201, first.text
    stopped = _disable(
        profile_id,
        first.json()["id"],
        actor_id,
        key="phase-ab-reauth-disable",
        headers=mfa_headers,
    )
    assert stopped.status_code == 200, stopped.text

    second = _authorize(
        profile_id,
        binding["id"],
        actor_id,
        key="phase-ab-reauth-2",
        cadence="daily",
        headers=mfa_headers,
    )
    assert second.status_code == 201, second.text
    assert second.json()["revision_number"] == 2
    assert second.json()["prior_schedule_id"] == first.json()["id"]
    assert second.json()["status"] == "active"

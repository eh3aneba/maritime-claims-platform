from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.core.security import create_access_token
from app.modules.auth.models import TotpMfaFactor
from app.modules.auth.service import create_auth_session
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
    ExternalDocumentSourceObservationReviewDecision,
    ExternalDocumentSourceObservationReviewDecisionReceipt,
)
from app.modules.external_document_sources.observation_review_decision_service import (
    decide_observation_review_handoff,
    ensure_observation_review_decision_integrity,
    get_observation_review_decision,
    list_pending_observation_review_handoffs,
)
from app.modules.external_document_sources.observation_review_handoff_service import (
    project_observation_review_handoff,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_discovery import _headers
from tests.test_external_document_source_due_tick_service_executor import _prepare
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_generation_3_change_detection import (
    _baseline_projection,
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
                secret_fingerprint="a" * 64,
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


def _changed_result() -> ExactItemMetadataResult:
    baseline = _baseline_projection()
    changed = baseline.__class__(
        provider_item_id=baseline.provider_item_id,
        parent_item_id=baseline.parent_item_id,
        item_kind=baseline.item_kind,
        display_name=baseline.display_name,
        mime_type_class=baseline.mime_type_class,
        byte_size=(baseline.byte_size or 0) + 41,
        modified_at=datetime(2026, 9, 20, 2, 0, tzinfo=UTC),
        version_token_hash="f" * 64,
    )
    return ExactItemMetadataResult(found=True, item=changed)


def _prepare_handoff(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    result: ExactItemMetadataResult,
):
    (
        actor_id,
        profile_id,
        _schedule_id,
        organization_id,
        document_id,
        dispatch_id,
        adapter,
    ) = _prepare(monkeypatch, suffix)
    adapter.result = result
    with TestingSessionLocal() as db:
        observation, _consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id="external-evidence-observer-v1",
            now=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        )
        assert outcome == "consumed"
        handoff, projected = project_observation_review_handoff(
            db,
            observation_execution_id=observation.id,
            projector_id="external-evidence-review-projector-v1",
            now=datetime(2026, 9, 20, 0, 1, tzinfo=UTC),
        )
        assert handoff is not None
        assert projected == "projected"
        handoff_id = handoff.id
        result_status = handoff.result_status
    return (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        handoff_id,
        result_status,
        adapter,
    )


def test_phase_ag_changed_approval_creates_one_narrow_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        handoff_id,
        result_status,
        adapter,
    ) = _prepare_handoff(monkeypatch, "ag-changed-approve", _changed_result())
    assert result_status == "changed"
    assert adapter.calls == 1

    with TestingSessionLocal() as db:
        decision, authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key="ag-changed-approve",
            decision_kind="approve_refresh",
            decision_reason="Human reviewer authorizes one narrow future refresh.",
            now=datetime(2026, 9, 20, 0, 2, tzinfo=UTC),
        )
        assert outcome == "decided"
        assert decision.status == "refresh_authorized"
        assert decision.current_document_id == document_id
        assert authorization is not None
        assert authorization.execution_limit == 1
        assert authorization.status == "authorized"
        assert authorization.observed_projection_hash == decision.observed_projection_hash
        ensure_observation_review_decision_integrity(db, decision)

        receipt = db.scalar(
            select(ExternalDocumentSourceObservationReviewDecisionReceipt).where(
                ExternalDocumentSourceObservationReviewDecisionReceipt.decision_id
                == decision.id
            )
        )
        assert receipt is not None
        assert receipt.event_type == "approve_refresh"
        assert receipt.actor_id == actor_id

        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action
                == "DECIDE_EXTERNAL_EVIDENCE_OBSERVATION_REVIEW_HANDOFF",
                AuditLog.entity_id == decision.id,
            )
        )
        assert audit is not None
        assert audit.user_id == actor_id
        assert audit.new_values["remote_content_read_performed"] is False
        assert audit.new_values["evidence_admitted"] is False
        decision_id = decision.id
        authorization_id = authorization.id

    assert adapter.calls == 1

    with TestingSessionLocal() as db:
        replay, replay_auth, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key="ag-changed-approve",
            decision_kind="approve_refresh",
            decision_reason="Human reviewer authorizes one narrow future refresh.",
        )
        assert outcome == "replayed"
        assert replay.id == decision_id
        assert replay_auth is not None
        assert replay_auth.id == authorization_id
        assert db.query(ExternalDocumentSourceObservationReviewDecision).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshAuthorization).count() == 1
        assert db.query(ExternalDocumentSourceObservationReviewDecisionReceipt).count() == 1

    assert adapter.calls == 1


def test_phase_ag_missing_acknowledgement_never_authorizes_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _document_id,
        handoff_id,
        result_status,
        adapter,
    ) = _prepare_handoff(
        monkeypatch,
        "ag-missing-ack",
        ExactItemMetadataResult(found=False, item=None, failure_code="not_found"),
    )
    assert result_status == "missing"

    with TestingSessionLocal() as db:
        decision, authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key="ag-missing-ack",
            decision_kind="acknowledge_missing",
            decision_reason="Human reviewer acknowledges that the source item is missing.",
        )
        assert outcome == "decided"
        assert decision.status == "missing_acknowledged"
        assert authorization is None
        assert db.query(ExternalDocumentSourceObservationRefreshAuthorization).count() == 0

    assert adapter.calls == 1


def test_phase_ag_missing_cannot_approve_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _document_id,
        handoff_id,
        _result_status,
        adapter,
    ) = _prepare_handoff(
        monkeypatch,
        "ag-missing-deny-refresh",
        ExactItemMetadataResult(found=False, item=None, failure_code="not_found"),
    )

    with TestingSessionLocal() as db:
        with pytest.raises(ExternalDocumentSourceConflictError):
            decide_observation_review_handoff(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                handoff_id=handoff_id,
                decided_by_id=actor_id,
                request_key="ag-missing-deny-refresh",
                decision_kind="approve_refresh",
                decision_reason="Human reviewer requests an invalid missing-item refresh.",
            )
        db.rollback()
        assert db.query(ExternalDocumentSourceObservationReviewDecision).count() == 0
        assert db.query(ExternalDocumentSourceObservationRefreshAuthorization).count() == 0

    assert adapter.calls == 1


def test_phase_ag_stale_current_document_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        handoff_id,
        _result_status,
        adapter,
    ) = _prepare_handoff(monkeypatch, "ag-stale-document", _changed_result())

    with TestingSessionLocal() as db:
        current = db.get(Document, document_id)
        assert current is not None
        current.is_current = False
        successor = Document(
            id=uuid4(),
            organization_id=current.organization_id,
            claim_id=current.claim_id,
            uploaded_by_id=current.uploaded_by_id,
            supersedes_document_id=current.id,
            document_family_id=current.document_family_id,
            filename="stale-successor.pdf",
            original_filename="stale-successor.pdf",
            mime_type=current.mime_type,
            file_size_bytes=current.file_size_bytes + 1,
            file_hash="9" * 64,
            storage_key="claims/stale-successor.pdf",
            version_number=current.version_number + 1,
            is_current=True,
        )
        db.add(successor)
        db.commit()

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="canonical Evidence changed",
        ):
            decide_observation_review_handoff(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                handoff_id=handoff_id,
                decided_by_id=actor_id,
                request_key="ag-stale-document",
                decision_kind="approve_refresh",
                decision_reason="Human reviewer attempts to approve a stale handoff.",
            )
        db.rollback()
        assert db.query(ExternalDocumentSourceObservationReviewDecision).count() == 0

    assert adapter.calls == 1


def test_phase_ag_historical_decision_survives_later_document_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        handoff_id,
        _result_status,
        adapter,
    ) = _prepare_handoff(monkeypatch, "ag-historical-decision", _changed_result())

    with TestingSessionLocal() as db:
        decision, _authorization, _outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key="ag-historical-decision",
            decision_kind="dismiss",
            decision_reason="Human reviewer dismisses this historical changed observation.",
        )
        decision_id = decision.id

    with TestingSessionLocal() as db:
        prior = db.get(Document, document_id)
        assert prior is not None
        prior.is_current = False
        successor = Document(
            id=uuid4(),
            organization_id=prior.organization_id,
            claim_id=prior.claim_id,
            uploaded_by_id=prior.uploaded_by_id,
            supersedes_document_id=prior.id,
            document_family_id=prior.document_family_id,
            filename="later-current.pdf",
            original_filename="later-current.pdf",
            mime_type=prior.mime_type,
            file_size_bytes=prior.file_size_bytes + 2,
            file_hash="8" * 64,
            storage_key="claims/later-current.pdf",
            version_number=prior.version_number + 1,
            is_current=True,
        )
        db.add(successor)
        db.commit()

    with TestingSessionLocal() as db:
        historical = get_observation_review_decision(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            decision_id=decision_id,
        )
        assert historical.id == decision_id
        assert historical.current_document_id == document_id
        assert historical.status == "dismissed"

    assert adapter.calls == 1


def test_phase_ag_pending_list_hides_decided_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _document_id,
        handoff_id,
        _result_status,
        adapter,
    ) = _prepare_handoff(monkeypatch, "ag-pending-list", _changed_result())

    with TestingSessionLocal() as db:
        pending = list_pending_observation_review_handoffs(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
        )
        assert [row.id for row in pending] == [handoff_id]

        decision, authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key="ag-pending-list",
            decision_kind="dismiss",
            decision_reason="Human reviewer dismisses this item after review.",
        )
        assert outcome == "decided"
        assert decision.status == "dismissed"
        assert authorization is None

    with TestingSessionLocal() as db:
        pending = list_pending_observation_review_handoffs(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
        )
        assert pending == []

    assert adapter.calls == 1


def test_phase_ag_nonhuman_or_unknown_actor_cannot_decide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _actor_id,
        profile_id,
        organization_id,
        _document_id,
        handoff_id,
        _result_status,
        adapter,
    ) = _prepare_handoff(monkeypatch, "ag-human-required", _changed_result())

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="active organization Admin",
        ):
            decide_observation_review_handoff(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                handoff_id=handoff_id,
                decided_by_id=uuid4(),
                request_key="ag-human-required",
                decision_kind="dismiss",
                decision_reason="A non-human identity must not be accepted as reviewer.",
            )
        db.rollback()
        assert db.query(ExternalDocumentSourceObservationReviewDecision).count() == 0

    assert adapter.calls == 1


def test_phase_ag_decision_endpoint_requires_admin_and_current_mfa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _document_id,
        handoff_id,
        _result_status,
        adapter,
    ) = _prepare_handoff(monkeypatch, "ag-api-mfa-admin", _changed_result())

    endpoint = (
        f"/api/v1/external-document-sources/profiles/{profile_id}"
        f"/observation-review-handoffs/{handoff_id}/decisions"
    )
    payload = {
        "request_key": "ag-api-mfa-admin",
        "decision_kind": "dismiss",
        "reason": "Human reviewer dismisses the observed change after explicit review.",
    }

    no_current_mfa = client.post(
        endpoint,
        headers=_headers(actor_id),
        json=payload,
    )
    assert no_current_mfa.status_code == 403, no_current_mfa.text
    assert "mfa" in no_current_mfa.text.lower()

    with TestingSessionLocal() as db:
        admin = db.get(User, actor_id)
        assert admin is not None
        handler = User(
            organization_id=organization_id,
            email="phase-ag-handler@example.com",
            full_name="Phase AG Handler",
            password_hash="local",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add(handler)
        db.commit()
        handler_id = handler.id

    non_admin = client.post(
        endpoint,
        headers=_headers(handler_id),
        json=payload,
    )
    assert non_admin.status_code == 403, non_admin.text

    allowed = client.post(
        endpoint,
        headers=_mfa_headers(actor_id),
        json=payload,
    )
    assert allowed.status_code == 201, allowed.text
    body = allowed.json()
    assert body["handoff_id"] == str(handoff_id)
    assert body["decision_kind"] == "dismiss"
    assert body["status"] == "dismissed"
    assert body["decided_by_id"] == str(actor_id)
    assert body["remote_content_read_performed"] is False
    assert body["evidence_admitted"] is False
    assert body["ai_executed"] is False

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationReviewDecision).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshAuthorization).count() == 0

    assert adapter.calls == 1

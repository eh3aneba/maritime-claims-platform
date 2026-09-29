from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
    ExternalDocumentSourceObservationReviewDecision,
    ExternalDocumentSourceObservationReviewDecisionReceipt,
)
from app.modules.external_document_sources.observation_review_decision_service import (
    decide_observation_review_handoff,
    ensure_observation_review_decision_integrity,
)
from app.modules.external_document_sources.observation_review_handoff_service import (
    project_observation_review_handoff,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_sftp_due_tick_service_executor import (
    _io_snapshot,
)
from tests.test_external_document_source_sftp_observation_review_handoff import (
    _PROJECTOR_ID,
    _observation,
    setup_function as _z_setup,
    teardown_function as _z_teardown,
)


def setup_function() -> None:
    _z_setup()


def teardown_function() -> None:
    _z_teardown()


def _prepare_handoff(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    *,
    mode: str,
):
    chain, adapter, observation_id, result_status = _observation(
        monkeypatch,
        f"sftp-phase-aa-{suffix}",
        mode=mode,
    )
    with TestingSessionLocal() as db:
        handoff, outcome = project_observation_review_handoff(
            db,
            observation_execution_id=observation_id,
            projector_id=_PROJECTOR_ID,
            now=datetime(2026, 9, 28, 18, 1, tzinfo=UTC),
        )
        assert handoff is not None
        assert outcome == "projected"
        assert handoff.provider_kind == "sftp"
        handoff_id = handoff.id
        organization_id = handoff.organization_id
        profile_id = handoff.profile_id

    return (
        chain,
        adapter,
        UUID(chain["requester_id"]),
        organization_id,
        profile_id,
        handoff_id,
        result_status,
    )


def test_phase_aa_changed_sftp_handoff_can_be_dismissed_and_replayed_without_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        chain,
        adapter,
        actor_id,
        organization_id,
        profile_id,
        handoff_id,
        result_status,
    ) = _prepare_handoff(monkeypatch, "cd", mode="changed")
    assert result_status == "changed"
    before = _io_snapshot(chain, adapter)

    reason = "Human reviewer dismisses this observed SFTP change."
    with TestingSessionLocal() as db:
        decision, authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key="sftp-phase-aa-changed-dismiss",
            decision_kind="dismiss",
            decision_reason=reason,
            now=datetime(2026, 9, 28, 18, 2, tzinfo=UTC),
        )
        assert outcome == "decided"
        assert decision.provider_kind == "sftp"
        assert decision.result_status == "changed"
        assert decision.decision_kind == "dismiss"
        assert decision.status == "dismissed"
        assert authorization is None
        ensure_observation_review_decision_integrity(db, decision)
        decision_id = decision.id

        assert db.query(ExternalDocumentSourceObservationReviewDecision).count() == 1
        assert (
            db.query(ExternalDocumentSourceObservationReviewDecisionReceipt).count()
            == 1
        )
        assert (
            db.query(ExternalDocumentSourceObservationRefreshAuthorization).count()
            == 0
        )

    assert _io_snapshot(chain, adapter) == before

    with TestingSessionLocal() as db:
        replay, replay_auth, replay_outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key="sftp-phase-aa-changed-dismiss",
            decision_kind="dismiss",
            decision_reason=reason,
        )
        assert replay_outcome == "replayed"
        assert replay.id == decision_id
        assert replay_auth is None

    assert _io_snapshot(chain, adapter) == before


@pytest.mark.parametrize(
    ("decision_kind", "expected_status"),
    (
        ("acknowledge_missing", "missing_acknowledged"),
        ("dismiss", "dismissed"),
    ),
)
def test_phase_aa_missing_sftp_handoff_supports_human_terminal_decisions(
    monkeypatch: pytest.MonkeyPatch,
    decision_kind: str,
    expected_status: str,
) -> None:
    (
        chain,
        adapter,
        actor_id,
        organization_id,
        profile_id,
        handoff_id,
        result_status,
    ) = _prepare_handoff(
        monkeypatch,
        "ma" if decision_kind == "acknowledge_missing" else "md",
        mode="missing",
    )
    assert result_status == "missing"
    before = _io_snapshot(chain, adapter)

    with TestingSessionLocal() as db:
        decision, authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key=f"sftp-phase-aa-missing-{decision_kind}",
            decision_kind=decision_kind,
            decision_reason="Human reviewer records the terminal SFTP missing-file decision.",
        )
        assert outcome == "decided"
        assert decision.provider_kind == "sftp"
        assert decision.result_status == "missing"
        assert decision.decision_kind == decision_kind
        assert decision.status == expected_status
        assert authorization is None
        ensure_observation_review_decision_integrity(db, decision)
        assert (
            db.query(ExternalDocumentSourceObservationRefreshAuthorization).count()
            == 0
        )

    assert _io_snapshot(chain, adapter) == before


def test_phase_aa_sftp_approve_refresh_remains_closed_before_decision_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        chain,
        adapter,
        actor_id,
        organization_id,
        profile_id,
        handoff_id,
        result_status,
    ) = _prepare_handoff(monkeypatch, "rb", mode="changed")
    assert result_status == "changed"
    before = _io_snapshot(chain, adapter)

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="17.6-AB",
        ):
            decide_observation_review_handoff(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                handoff_id=handoff_id,
                decided_by_id=actor_id,
                request_key="sftp-phase-aa-approve-must-remain-closed",
                decision_kind="approve_refresh",
                decision_reason="This must not create SFTP refresh authority in AA.",
            )
        db.rollback()

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationReviewDecision).count() == 0
        assert (
            db.query(ExternalDocumentSourceObservationReviewDecisionReceipt).count()
            == 0
        )
        assert (
            db.query(ExternalDocumentSourceObservationRefreshAuthorization).count()
            == 0
        )

    assert _io_snapshot(chain, adapter) == before

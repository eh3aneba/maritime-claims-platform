from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.modules.external_document_sources import sftp_lifecycle_instrumentation as instrumentation
from tests.db_harness import TestingSessionLocal


def _spec(*, defer: bool = False) -> instrumentation._LifecycleSpec:
    return instrumentation._LifecycleSpec(
        module_name="tests.synthetic",
        function_name="operation",
        operation="due_tick_observation",
        outcomes={"completed": "completed", "replayed": "replayed"},
        defer_new_success_when_uncommitted=defer,
    )


def test_ae_b_new_success_is_emitted_only_after_internal_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict[str, object]] = []
    transaction_state_at_emit: list[bool] = []

    def capture(**payload) -> None:
        events.append(payload)
        transaction_state_at_emit.append(db.in_transaction())

    monkeypatch.setattr(instrumentation, "emit_sftp_lifecycle", capture)

    def operation(session):
        session.commit()
        return SimpleNamespace(provider_kind="sftp"), "completed"

    wrapped = instrumentation._wrap(operation, _spec())
    with TestingSessionLocal() as db:
        result = wrapped(db)

    assert result[1] == "completed"
    assert [event["outcome"] for event in events] == ["completed"]
    assert transaction_state_at_emit == [False]


def test_ae_b_replay_emits_only_after_prior_integrity_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    def capture(**_payload) -> None:
        order.append("telemetry")

    monkeypatch.setattr(instrumentation, "emit_sftp_lifecycle", capture)

    def operation(_session):
        order.append("integrity_verified")
        return SimpleNamespace(provider_kind="sftp"), "replayed"

    wrapped = instrumentation._wrap(operation, _spec())
    with TestingSessionLocal() as db:
        result = wrapped(db)

    assert result[1] == "replayed"
    assert order == ["integrity_verified", "telemetry"]


def test_ae_b_forced_commit_failure_never_emits_success(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        instrumentation,
        "emit_sftp_lifecycle",
        lambda **payload: events.append(payload),
    )
    monkeypatch.setattr(
        instrumentation,
        "_call_is_sftp_before",
        lambda *_args, **_kwargs: True,
    )

    def operation(session):
        session.commit()
        return SimpleNamespace(provider_kind="sftp"), "completed"

    wrapped = instrumentation._wrap(operation, _spec())
    with TestingSessionLocal() as db:
        monkeypatch.setattr(
            db,
            "commit",
            lambda: (_ for _ in ()).throw(SQLAlchemyError("forced commit failure SECRET")),
        )
        with pytest.raises(SQLAlchemyError):
            wrapped(db)

    assert [event["outcome"] for event in events] == ["failed"]
    assert events[0]["failure_code"] == "db_commit_failed"
    assert all(event["outcome"] != "completed" for event in events)
    assert "SECRET" not in str(events)


def test_ae_b_outer_transaction_success_waits_for_after_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        instrumentation,
        "emit_sftp_lifecycle",
        lambda **payload: events.append(payload),
    )

    def operation(_session, **_kwargs):
        return SimpleNamespace(provider_kind="sftp"), "completed"

    wrapped = instrumentation._wrap(operation, _spec(defer=True))
    with TestingSessionLocal() as db:
        result = wrapped(db, commit_transaction=False)
        assert result[1] == "completed"
        assert events == []
        db.commit()
        assert [event["outcome"] for event in events] == ["completed"]


def test_ae_b_outer_transaction_rollback_clears_pending_success(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        instrumentation,
        "emit_sftp_lifecycle",
        lambda **payload: events.append(payload),
    )

    def operation(_session, **_kwargs):
        return SimpleNamespace(provider_kind="sftp"), "completed"

    wrapped = instrumentation._wrap(operation, _spec(defer=True))
    with TestingSessionLocal() as db:
        wrapped(db, commit_transaction=False)
        assert events == []
        db.rollback()
        db.commit()

    assert events == []


def test_ae_b_non_sftp_transition_is_unchanged_and_uninstrumented(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        instrumentation,
        "emit_sftp_lifecycle",
        lambda **payload: events.append(payload),
    )

    def operation(session):
        session.commit()
        return SimpleNamespace(provider_kind="sharepoint"), "completed"

    wrapped = instrumentation._wrap(operation, _spec())
    with TestingSessionLocal() as db:
        result = wrapped(db)

    assert result[1] == "completed"
    assert events == []

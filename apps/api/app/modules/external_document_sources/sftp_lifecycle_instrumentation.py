from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.models import ExternalDocumentSourceProfile
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_lifecycle_telemetry import (
    emit_sftp_lifecycle,
    sftp_lifecycle_started_ns,
)


_PENDING_KEY = "mcri.sftp.lifecycle.pending"
_INSTALLED = False


@dataclass(frozen=True)
class _LifecycleSpec:
    module_name: str
    function_name: str
    operation: str
    outcomes: dict[str, str]
    defer_new_success_when_uncommitted: bool = False


_SPECS = (
    _LifecycleSpec(
        "app.modules.external_document_sources.due_tick_observation_service",
        "execute_due_tick_observation",
        "due_tick_observation",
        {"completed": "completed", "replayed": "replayed"},
        defer_new_success_when_uncommitted=True,
    ),
    _LifecycleSpec(
        "app.modules.external_document_sources.observation_review_handoff_service",
        "project_observation_review_handoff",
        "review_handoff",
        {"projected": "projected", "replayed": "replayed", "ineligible": "rejected"},
    ),
    _LifecycleSpec(
        "app.modules.external_document_sources.observation_review_decision_service",
        "decide_observation_review_handoff",
        "review_decision",
        {"decided": "completed", "replayed": "replayed"},
    ),
    _LifecycleSpec(
        "app.modules.external_document_sources.observation_refresh_execution_service",
        "execute_observation_refresh_authorization",
        "refresh_execution",
        {"completed": "completed", "replayed": "replayed"},
    ),
    _LifecycleSpec(
        "app.modules.external_document_sources.observation_refresh_admission_authorization_service",
        "authorize_observation_refresh_admission",
        "admission_authorization",
        {"authorized": "authorized", "replayed": "replayed"},
    ),
    _LifecycleSpec(
        "app.modules.external_document_sources.observation_refresh_admission_execution_service",
        "execute_observation_refresh_admission",
        "admission_execution",
        {"admitted": "admitted", "replayed": "replayed"},
    ),
    _LifecycleSpec(
        "app.modules.external_document_sources.processing_release_service",
        "grant_processing_release",
        "processing_release",
        {"granted": "released", "replayed": "replayed"},
    ),
    _LifecycleSpec(
        "app.modules.external_document_sources.processing_release_service",
        "revoke_processing_release",
        "processing_release",
        {"revoked": "revoked", "replayed": "replayed"},
    ),
    _LifecycleSpec(
        "app.modules.external_document_sources.recurring_baseline_transition_service",
        "establish_recurring_baseline_transition",
        "baseline_transition",
        {"established": "established", "replayed": "replayed"},
    ),
)


def _first_entity(result: Any) -> Any | None:
    if isinstance(result, tuple) and result:
        return result[0]
    return result


def _result_outcome(result: Any) -> str | None:
    if not isinstance(result, tuple):
        return None
    for value in reversed(result):
        if isinstance(value, str):
            return value
    return None


def _profile_is_sftp(db: Session, profile_id: Any) -> bool:
    if profile_id is None:
        return False
    try:
        with db.no_autoflush:
            profile = db.get(ExternalDocumentSourceProfile, profile_id)
        return profile is not None and profile.provider_kind == "sftp"
    except Exception:
        # Telemetry discovery is non-authoritative. If it cannot determine the
        # provider safely, the governed operation continues without telemetry.
        return False


def _call_is_sftp_before(
    db: Session,
    *,
    operation: str,
    kwargs: dict[str, Any],
) -> bool:
    if _profile_is_sftp(db, kwargs.get("profile_id")):
        return True
    if operation == "review_handoff":
        observation_id = kwargs.get("observation_execution_id")
        if observation_id is None:
            return False
        try:
            with db.no_autoflush:
                observation = db.get(
                    ExternalDocumentSourceDueTickObservationExecution,
                    observation_id,
                )
            return observation is not None and observation.provider_kind == "sftp"
        except Exception:
            return False
    return False


def _result_is_sftp(db: Session, result: Any, *, fallback: bool) -> bool:
    entity = _first_entity(result)
    if entity is None:
        return fallback
    provider_kind = getattr(entity, "provider_kind", None)
    if provider_kind is not None:
        return provider_kind == "sftp"
    profile_id = getattr(entity, "profile_id", None)
    if profile_id is not None:
        return _profile_is_sftp(db, profile_id)
    return fallback


def _failure_code(exc: BaseException) -> str | None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        return "not_found"
    if isinstance(exc, ExternalDocumentSourceValidationError):
        return "validation_failed"
    if isinstance(exc, ExternalDocumentSourceConflictError):
        return "conflict"
    if isinstance(exc, SQLAlchemyError):
        return "db_commit_failed"
    return None


def _queue_after_commit(
    db: Session,
    *,
    operation: str,
    outcome: str,
    started_ns: int,
) -> None:
    # A deferred success is meaningful only when the governed operation is
    # already participating in a real outer transaction. Telemetry must never
    # create a transaction merely so it can later observe commit/rollback.
    if not db.in_transaction():
        return
    pending = db.info.setdefault(_PENDING_KEY, [])
    pending.append((operation, outcome, started_ns))


def _after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, [])
    for operation, outcome, started_ns in pending:
        emit_sftp_lifecycle(
            operation=operation,
            outcome=outcome,
            started_ns=started_ns,
        )


def _clear_pending(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)


def _wrap(original: Callable[..., Any], spec: _LifecycleSpec) -> Callable[..., Any]:
    if getattr(original, "__mcri_sftp_lifecycle_wrapped__", False):
        return original

    @wraps(original)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not args or not isinstance(args[0], Session):
            return original(*args, **kwargs)
        db: Session = args[0]
        started_ns = sftp_lifecycle_started_ns()
        sftp_before = _call_is_sftp_before(
            db,
            operation=spec.operation,
            kwargs=kwargs,
        )
        try:
            result = original(*args, **kwargs)
        except BaseException as exc:
            if sftp_before:
                emit_sftp_lifecycle(
                    operation=spec.operation,
                    outcome="failed",
                    started_ns=started_ns,
                    failure_code=_failure_code(exc),
                )
            raise

        if not _result_is_sftp(db, result, fallback=sftp_before):
            return result
        raw_outcome = _result_outcome(result)
        lifecycle_outcome = spec.outcomes.get(raw_outcome or "")
        if lifecycle_outcome is None:
            return result

        # Replay paths are returned only after the underlying service has
        # verified integrity of the durable prior result. They do not need a
        # new commit and are emitted immediately after that verified return.
        if lifecycle_outcome == "replayed":
            emit_sftp_lifecycle(
                operation=spec.operation,
                outcome="replayed",
                started_ns=started_ns,
            )
            return result

        # Due-tick worker execution can deliberately participate in an outer
        # transaction. Queue its success until SQLAlchemy confirms that outer
        # commit. A rollback clears the queue and can never emit success.
        if (
            spec.defer_new_success_when_uncommitted
            and kwargs.get("commit_transaction", True) is False
        ):
            _queue_after_commit(
                db,
                operation=spec.operation,
                outcome=lifecycle_outcome,
                started_ns=started_ns,
            )
            return result

        # All other governed mutation services commit internally before their
        # success outcome is returned. Therefore this point is post-commit.
        emit_sftp_lifecycle(
            operation=spec.operation,
            outcome=lifecycle_outcome,
            started_ns=started_ns,
        )
        return result

    setattr(wrapped, "__mcri_sftp_lifecycle_wrapped__", True)
    return wrapped


def _replace_imported_references(original: Callable[..., Any], wrapped: Callable[..., Any]) -> None:
    # Routers and workers use `from service import function`. Replace already
    # imported references by object identity so every invocation path observes
    # the same non-authoritative instrumentation wrapper.
    for loaded in list(sys.modules.values()):
        if loaded is None:
            continue
        namespace = getattr(loaded, "__dict__", None)
        if not isinstance(namespace, dict):
            continue
        for name, value in list(namespace.items()):
            if value is original:
                namespace[name] = wrapped


def install_sftp_lifecycle_instrumentation() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _clear_pending)
    event.listen(Session, "after_soft_rollback", lambda session, _previous: _clear_pending(session))

    for spec in _SPECS:
        module = importlib.import_module(spec.module_name)
        original = getattr(module, spec.function_name)
        wrapped = _wrap(original, spec)
        if wrapped is original:
            continue
        setattr(module, spec.function_name, wrapped)
        _replace_imported_references(original, wrapped)

    _INSTALLED = True

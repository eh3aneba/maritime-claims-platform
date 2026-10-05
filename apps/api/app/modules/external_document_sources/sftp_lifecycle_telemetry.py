from __future__ import annotations

import json
import logging
import time


_LOGGER = logging.getLogger("mcri.sftp.lifecycle")
_EVENT = "mcri.sftp.lifecycle"
_OPERATIONS = frozenset(
    {
        "due_tick_observation",
        "review_handoff",
        "review_decision",
        "refresh_execution",
        "admission_authorization",
        "admission_execution",
        "processing_release",
        "baseline_transition",
    }
)
_OUTCOMES = frozenset(
    {
        "completed",
        "replayed",
        "rejected",
        "failed",
        "authorized",
        "admitted",
        "released",
        "revoked",
        "established",
        "projected",
    }
)
_FAILURE_CODES = frozenset(
    {
        "db_commit_failed",
        "integrity_verification_failed",
        "conflict",
        "validation_failed",
        "not_found",
    }
)


def sftp_lifecycle_started_ns() -> int:
    return time.perf_counter_ns()


def emit_sftp_lifecycle(
    *,
    operation: str,
    outcome: str,
    started_ns: int,
    failure_code: str | None = None,
) -> None:
    """Emit bounded operational telemetry without changing authority semantics.

    The event intentionally accepts no organization, claim, profile, document,
    binding, locator, credential, content or exception-text fields. Invalid
    telemetry values are dropped rather than allowed to affect the governed
    transaction that called this helper.
    """

    if operation not in _OPERATIONS or outcome not in _OUTCOMES:
        return

    try:
        elapsed_ns = max(0, time.perf_counter_ns() - int(started_ns))
        payload: dict[str, object] = {
            "event": _EVENT,
            "operation": operation,
            "outcome": outcome,
            "duration_ms": elapsed_ns // 1_000_000,
        }
        if failure_code in _FAILURE_CODES:
            payload["failure_code"] = failure_code
        _LOGGER.info(
            "%s",
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
    except Exception:
        # Operational telemetry is explicitly non-authoritative. Logging must
        # never widen authority or change transaction success/failure behavior.
        return

from __future__ import annotations

import json
import logging

from app.modules.external_document_sources import sftp_lifecycle_telemetry as telemetry


def test_ae_b_sftp_lifecycle_event_is_bounded_and_privacy_safe(caplog) -> None:
    secret_markers = (
        "sftp.customer.example",
        "/claims/secret/path.pdf",
        "sftp-user-name",
        "vault://prod/credential-reference",
        "PRIVATE-KEY-MARKER",
        "CUSTOMER-CONTENT-MARKER",
    )

    caplog.set_level(logging.INFO, logger="mcri.sftp.lifecycle")
    started = telemetry.sftp_lifecycle_started_ns()
    telemetry.emit_sftp_lifecycle(
        operation="baseline_transition",
        outcome="established",
        started_ns=started,
    )

    records = [
        record for record in caplog.records if record.name == "mcri.sftp.lifecycle"
    ]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert set(payload) == {"event", "operation", "outcome", "duration_ms"}
    assert payload["event"] == "mcri.sftp.lifecycle"
    assert payload["operation"] == "baseline_transition"
    assert payload["outcome"] == "established"
    assert isinstance(payload["duration_ms"], int)
    assert payload["duration_ms"] >= 0
    rendered = records[0].getMessage()
    for marker in secret_markers:
        assert marker not in rendered


def test_ae_b_sftp_lifecycle_failure_code_is_finite() -> None:
    class CapturingLogger:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def info(self, _format: str, message: str) -> None:
            self.messages.append(message)

    logger = CapturingLogger()
    original = telemetry._LOGGER
    telemetry._LOGGER = logger  # type: ignore[assignment]
    try:
        started = telemetry.sftp_lifecycle_started_ns()
        telemetry.emit_sftp_lifecycle(
            operation="refresh_execution",
            outcome="failed",
            started_ns=started,
            failure_code="raw database exception: password=do-not-log",
        )
    finally:
        telemetry._LOGGER = original

    assert len(logger.messages) == 1
    payload = json.loads(logger.messages[0])
    assert "failure_code" not in payload
    assert "password" not in logger.messages[0]


def test_ae_b_sftp_lifecycle_logging_failure_never_changes_caller_semantics() -> None:
    class BrokenLogger:
        def info(self, *_args, **_kwargs) -> None:
            raise RuntimeError("logging backend unavailable")

    original = telemetry._LOGGER
    telemetry._LOGGER = BrokenLogger()  # type: ignore[assignment]
    try:
        telemetry.emit_sftp_lifecycle(
            operation="processing_release",
            outcome="released",
            started_ns=telemetry.sftp_lifecycle_started_ns(),
        )
    finally:
        telemetry._LOGGER = original


def test_ae_b_sftp_lifecycle_drops_unknown_operation_or_outcome(caplog) -> None:
    caplog.set_level(logging.INFO, logger="mcri.sftp.lifecycle")
    started = telemetry.sftp_lifecycle_started_ns()
    telemetry.emit_sftp_lifecycle(
        operation="arbitrary-customer-action",
        outcome="completed",
        started_ns=started,
    )
    telemetry.emit_sftp_lifecycle(
        operation="review_decision",
        outcome="arbitrary-customer-result",
        started_ns=started,
    )
    assert not [record for record in caplog.records if record.name == "mcri.sftp.lifecycle"]

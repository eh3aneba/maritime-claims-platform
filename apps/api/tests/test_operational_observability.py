from __future__ import annotations

import json
import logging
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.modules.health.router as health_router
from app.core.observability import request_observability_middleware
from app.main import app


client = TestClient(app)


def _request_events(caplog) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for record in caplog.records:
        if record.name != "mcri.request":
            continue
        try:
            payload = json.loads(record.getMessage())
        except json.JSONDecodeError:
            continue
        events.append(payload)
    return events


def test_preserves_safe_inbound_request_id_and_logs_completion(caplog) -> None:
    request_id = "phase14.1-test:abc-123"
    with caplog.at_level(logging.INFO, logger="mcri.request"):
        response = client.get("/api/v1/health/live", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id

    matching = [event for event in _request_events(caplog) if event.get("request_id") == request_id]
    assert matching
    event = matching[-1]
    assert event["event"] == "http_request_completed"
    assert event["method"] == "GET"
    assert event["path"] == "/api/v1/health/live"
    assert event["status_code"] == 200
    assert isinstance(event["duration_ms"], (int, float))
    assert event["duration_ms"] >= 0


def test_generates_request_id_when_inbound_value_is_missing_or_unsafe() -> None:
    generated = client.get("/api/v1/health/live")
    unsafe = client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id with spaces"})

    assert generated.status_code == 200
    assert unsafe.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{32}", generated.headers["X-Request-ID"])
    assert re.fullmatch(r"[0-9a-f]{32}", unsafe.headers["X-Request-ID"])


def test_failure_log_remains_metadata_only_without_exception_text_or_traceback(caplog) -> None:
    failing_app = FastAPI()
    failing_app.middleware("http")(request_observability_middleware)

    @failing_app.get("/boom")
    def boom() -> None:
        raise RuntimeError("sensitive-claim-content-must-not-be-logged")

    failing_client = TestClient(failing_app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="mcri.request"):
        response = failing_client.get("/boom", headers={"X-Request-ID": "failure-test-123"})

    assert response.status_code == 500
    matching_records = [
        record
        for record in caplog.records
        if record.name == "mcri.request" and "failure-test-123" in record.getMessage()
    ]
    assert matching_records
    record = matching_records[-1]
    assert record.exc_info is None
    assert "sensitive-claim-content-must-not-be-logged" not in record.getMessage()

    event = json.loads(record.getMessage())
    assert event["event"] == "http_request_failed"
    assert event["request_id"] == "failure-test-123"
    assert event["method"] == "GET"
    assert event["path"] == "/boom"
    assert event["status_code"] == 500


def test_liveness_and_compatibility_health_are_process_only() -> None:
    live = client.get("/api/v1/health/live")
    compatibility = client.get("/api/v1/health")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert live.json()["check"] == "liveness"
    assert compatibility.status_code == 200
    assert compatibility.json()["status"] == "ok"


def test_readiness_is_200_when_database_probe_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(health_router, "database_ready", lambda: True)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["dependencies"] == {"database": "ok"}


def test_readiness_fails_closed_without_exposing_database_error(monkeypatch) -> None:
    monkeypatch.setattr(health_router, "database_ready", lambda: False)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["dependencies"] == {"database": "unavailable"}
    serialized = json.dumps(payload).lower()
    assert "postgresql" not in serialized
    assert "password" not in serialized
    assert "database_url" not in serialized

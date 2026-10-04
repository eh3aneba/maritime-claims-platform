from types import SimpleNamespace

from fastapi import Response, status

import app.modules.health.router as health


def _settings(enabled: bool):
    return SimpleNamespace(external_evidence_live_sftp_adapters_enabled=enabled)


def test_readiness_reports_sftp_disabled_without_runtime_probe(monkeypatch) -> None:
    monkeypatch.setattr(health, "database_ready", lambda: True)
    monkeypatch.setattr(health, "get_settings", lambda: _settings(False))

    def _must_not_be_needed():
        raise AssertionError("disabled SFTP readiness must not inspect runtime registration")

    monkeypatch.setattr(health, "sftp_runtime_registration_complete", _must_not_be_needed)
    response = Response()

    payload = health.readiness(response)

    assert response.status_code == status.HTTP_200_OK
    assert payload["status"] == "ready"
    assert payload["dependencies"] == {
        "database": "ok",
        "sftp_runtime": "disabled",
    }


def test_readiness_reports_registered_sftp_without_provider_io(monkeypatch) -> None:
    monkeypatch.setattr(health, "database_ready", lambda: True)
    monkeypatch.setattr(health, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(
        health,
        "sftp_runtime_registration_complete",
        lambda: True,
    )
    response = Response()

    payload = health.readiness(response)

    assert response.status_code == status.HTTP_200_OK
    assert payload["status"] == "ready"
    assert payload["dependencies"] == {
        "database": "ok",
        "sftp_runtime": "registered",
    }


def test_readiness_fails_closed_when_enabled_sftp_is_not_registered(monkeypatch) -> None:
    monkeypatch.setattr(health, "database_ready", lambda: True)
    monkeypatch.setattr(health, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(
        health,
        "sftp_runtime_registration_complete",
        lambda: False,
    )
    response = Response()

    payload = health.readiness(response)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert payload["status"] == "not_ready"
    assert payload["dependencies"] == {
        "database": "ok",
        "sftp_runtime": "unavailable",
    }


def test_readiness_keeps_database_failure_and_sftp_state_separate(monkeypatch) -> None:
    monkeypatch.setattr(health, "database_ready", lambda: False)
    monkeypatch.setattr(health, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(
        health,
        "sftp_runtime_registration_complete",
        lambda: True,
    )
    response = Response()

    payload = health.readiness(response)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert payload["status"] == "not_ready"
    assert payload["dependencies"] == {
        "database": "unavailable",
        "sftp_runtime": "registered",
    }

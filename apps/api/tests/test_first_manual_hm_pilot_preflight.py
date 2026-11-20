"""First bounded H&M machinery pilot — fail-closed application preflight.

Offline synthetic configuration checks only; no host, customer, OCR or secrets.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import preflight
from app.core.first_manual_hm_pilot import first_manual_hm_pilot_errors


def _safe(tmp_path: Path):
    return SimpleNamespace(
        app_env="pilot",
        cors_origins=["http://localhost:3000"],
        next_public_api_base_url="http://localhost:8000/api/v1",
        secret_key="synthetic-only-" + "a" * 40,
        database_url="postgresql+psycopg://test:synthetic-secret@db:5432/synthetic",
        ai_provider="disabled",
        ai_model="",
        openai_api_key="",
        allow_external_ai_restricted=False,
        ai_local_experimental_enabled=False,
        ai_production_control_plane_enabled=False,
        external_evidence_live_provider_adapters_enabled=False,
        external_evidence_live_sftp_adapters_enabled=False,
        ocr_enabled=False,
        s3_foundation_enabled=False,
        storage_backend="local",
        local_storage_path=str(tmp_path),
        malware_scan_enabled=True,
        clamav_host="clamav",
        clamav_port=3310,
        clamav_timeout_seconds=1.0,
    )


def test_first_pilot_manual_only_configuration_passes_without_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    cfg = _safe(tmp_path)
    monkeypatch.setattr(preflight, "get_settings", lambda: cfg)
    monkeypatch.setattr(preflight, "ping_clamd", lambda **_kwargs: None)
    errors, warnings = preflight.run_preflight(require_db=False)
    assert errors == []
    assert any("AI_PROVIDER is disabled" in warning for warning in warnings)
    assert first_manual_hm_pilot_errors(cfg) == []


@pytest.mark.parametrize(("field", "bad"), [
    ("ai_provider", "ollama_local"),
    ("ai_provider", "openai"),
    ("ai_model", "qwen3:1.7b"),
    ("openai_api_key", "private-secret-marker"),
    ("allow_external_ai_restricted", True),
    ("ai_local_experimental_enabled", True),
    ("ai_production_control_plane_enabled", True),
    ("external_evidence_live_provider_adapters_enabled", True),
    ("external_evidence_live_sftp_adapters_enabled", True),
    ("ocr_enabled", True),
])
def test_first_pilot_rejects_each_expanded_scope_before_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str, bad,
) -> None:
    cfg = _safe(tmp_path)
    setattr(cfg, field, bad)
    monkeypatch.setattr(preflight, "get_settings", lambda: cfg)
    monkeypatch.setattr(preflight, "ping_clamd", lambda **_kwargs: None)
    errors, _ = preflight.run_preflight(require_db=False)
    assert first_manual_hm_pilot_errors(cfg)
    assert any("First manual H&M pilot" in item for item in errors)
    assert "private-secret-marker" not in "\n".join(errors)


@pytest.mark.parametrize("field", [
    "ai_provider", "ai_model", "openai_api_key", "allow_external_ai_restricted",
    "ai_local_experimental_enabled", "ai_production_control_plane_enabled",
    "external_evidence_live_provider_adapters_enabled",
    "external_evidence_live_sftp_adapters_enabled", "ocr_enabled",
])
def test_first_pilot_rejects_missing_safety_configuration(
    tmp_path: Path, field: str,
) -> None:
    cfg = _safe(tmp_path)
    delattr(cfg, field)
    assert first_manual_hm_pilot_errors(cfg)


def test_first_pilot_gate_does_not_restrict_unrelated_development_or_staging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # Production/staging AI controls retain their existing dedicated policies.
    cfg = _safe(tmp_path)
    cfg.app_env = "test"
    cfg.ocr_enabled = True
    cfg.ai_model = "synthetic-development-model"
    cfg.external_evidence_live_sftp_adapters_enabled = True
    monkeypatch.setattr(preflight, "get_settings", lambda: cfg)
    monkeypatch.setattr(preflight, "ping_clamd", lambda **_kwargs: None)
    errors, _ = preflight.run_preflight(require_db=False)
    assert errors == []


def test_first_pilot_compose_preflight_receives_real_worker_feature_switches() -> None:
    root = Path(__file__).resolve().parents[3]
    template = (root / ".env.pilot.example").read_text(encoding="utf-8")
    config = (root / "docker-compose.yml").read_text(encoding="utf-8")
    preflight_section = config.split("\n  preflight:", 1)[1].split("\n  api:", 1)[0]
    worker_section = config.split("\n  worker:", 1)[1].split("\n  governance-webhook-worker:", 1)[0]
    assert "OCR_ENABLED=false" in template
    assert "AI_PROVIDER=disabled" in template
    for key in (
        "AI_LOCAL_EXPERIMENTAL_ENABLED", "AI_PRODUCTION_CONTROL_PLANE_ENABLED",
        "EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED",
        "EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED",
    ):
        assert f"{key}=false" in template
        assert f"{key}: ${{{key}:-false}}" in preflight_section
    assert "OCR_ENABLED: ${OCR_ENABLED:-true}" in preflight_section
    assert "OCR_ENABLED: ${OCR_ENABLED:-true}" in worker_section

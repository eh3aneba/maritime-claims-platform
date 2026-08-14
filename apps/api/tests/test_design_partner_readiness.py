from pathlib import Path

from app.core.config import get_settings
from app.core.preflight import run_preflight
from app.demo.mt_orion_fixture import AI_CASES, DOC_TYPES


def _settings(monkeypatch, tmp_path: Path, **values):
    base = {
        "APP_ENV": "development",
        "SECRET_KEY": "replace-with-a-long-random-secret",
        "DATABASE_URL": "postgresql+psycopg://maritime:change-me-in-local-env@localhost:5432/maritime_claims",
        "CORS_ALLOWED_ORIGINS": "http://localhost:3000",
        "LOCAL_STORAGE_PATH": str(tmp_path / "evidence"),
        "AI_PROVIDER": "disabled",
        "MALWARE_SCAN_ENABLED": "false",
    }
    base.update(values)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_development_preflight_allows_local_defaults(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    errors, warnings = run_preflight(require_db=False)
    assert errors == []
    assert any("AI_PROVIDER is disabled" in warning for warning in warnings)


def test_pilot_preflight_rejects_default_secrets(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, APP_ENV="pilot")
    errors, _ = run_preflight(require_db=False)
    assert any("SECRET_KEY" in error for error in errors)
    assert any("DATABASE_URL" in error for error in errors)
    assert any("MALWARE_SCAN_ENABLED" in error for error in errors)


def test_pilot_preflight_requires_malware_scanning(monkeypatch, tmp_path):
    _settings(
        monkeypatch,
        tmp_path,
        APP_ENV="pilot",
        SECRET_KEY="a-secure-random-pilot-secret-with-more-than-32-characters",
        DATABASE_URL="postgresql+psycopg://maritime:secure-password@localhost:5432/maritime_claims",
    )
    errors, _ = run_preflight(require_db=False)
    assert errors == ["MALWARE_SCAN_ENABLED must be true for pilot, staging and production"]


def test_enabled_malware_scanner_is_checked(monkeypatch, tmp_path):
    calls = []
    _settings(monkeypatch, tmp_path, MALWARE_SCAN_ENABLED="true", CLAMAV_HOST="clamav")
    monkeypatch.setattr(
        "app.core.preflight.ping_clamd",
        lambda **kwargs: calls.append(kwargs),
    )
    errors, _ = run_preflight(require_db=False)
    assert errors == []
    assert calls == [{"host": "clamav", "port": 3310, "timeout_seconds": 30.0}]


def test_preflight_rejects_wildcard_cors(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, CORS_ALLOWED_ORIGINS="*")
    errors, _ = run_preflight(require_db=False)
    assert any("Wildcard CORS" in error for error in errors)


def test_demo_fixture_covers_full_mt_orion_evidence_pack():
    assert len(DOC_TYPES) == 9
    assert len(AI_CASES) == 8
    assert "01_claim_notification.docx" in DOC_TYPES
    assert "09_invoice.xlsx" in AI_CASES


def test_design_partner_seed_is_full_and_idempotent(monkeypatch, tmp_path):
    from sqlalchemy import func, select

    from app.core.config import get_settings
    from app.demo import seed_mt_orion
    from app.modules.assessments.models import InitialAssessment
    from app.modules.claims.models import Claim
    from app.modules.documents.models import Document
    from tests.db_harness import TestingSessionLocal, reset_database

    reset_database()
    settings = get_settings()
    previous_storage = settings.local_storage_path
    settings.local_storage_path = str(tmp_path / "demo-evidence")
    fixture_dir = Path(__file__).resolve().parents[3] / "docs" / "pilot" / "mt-orion" / "documents"
    monkeypatch.setenv("MCRI_DEMO_PASSWORD", "Strong-Demo-2026!")
    monkeypatch.setenv("MCRI_DEMO_FIXTURE_DIR", str(fixture_dir))
    monkeypatch.setattr(seed_mt_orion, "create_session", TestingSessionLocal)
    try:
        seed_mt_orion.main()
        with TestingSessionLocal() as db:
            claim = db.scalar(select(Claim).where(Claim.external_reference == seed_mt_orion.DEMO_EXTERNAL_REFERENCE))
            assert claim is not None
            assert db.scalar(select(func.count()).select_from(Document).where(Document.claim_id == claim.id)) == 9
            assessment = db.scalar(select(InitialAssessment).where(InitialAssessment.claim_id == claim.id))
            assert assessment is not None and assessment.is_preliminary is True

        seed_mt_orion.main()
        with TestingSessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Claim).where(Claim.external_reference == seed_mt_orion.DEMO_EXTERNAL_REFERENCE)) == 1
    finally:
        settings.local_storage_path = previous_storage


def test_create_session_binds_configured_engine(monkeypatch):
    """CLI/worker sessions must be executable without FastAPI dependency injection."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool

    import app.db.session as session_module

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(session_module, "get_engine", lambda: engine)
    with session_module.create_session() as db:
        assert db.scalar(text("SELECT 1")) == 1


def test_standalone_worker_registers_all_orm_models():
    """Importing the worker must configure relationship targets without API router side effects."""
    from sqlalchemy.orm import configure_mappers

    import app.workers.document_worker  # noqa: F401

    configure_mappers()


def test_default_demo_email_is_login_schema_compatible():
    from app.modules.auth.schemas import LoginRequest

    payload = LoginRequest(
        organization_slug="pilot",
        email="manager@demo.mcri.app",
        password="Strong-Demo-2026!",
    )
    assert str(payload.email) == "manager@demo.mcri.app"

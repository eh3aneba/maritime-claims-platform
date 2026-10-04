from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_session
from app.modules.external_document_sources.sftp_production_hardening import (
    install_sftp_production_hardening,
    sftp_runtime_registration_complete,
)

# app.main imports this module before startup live-SFTP registration. Installing
# the guard here is pure in-process work: no DNS, secret, provider or storage I/O.
install_sftp_production_hardening()

router = APIRouter(tags=["health"])
_SERVICE = "maritime-claims-api"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def database_ready() -> bool:
    """Return database connectivity only; never expose connection/error details."""
    try:
        with create_session() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _sftp_runtime_state() -> str:
    settings = get_settings()
    if not settings.external_evidence_live_sftp_adapters_enabled:
        return "disabled"
    if sftp_runtime_registration_complete():
        return "registered"
    return "unavailable"


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {
        "status": "ok",
        "service": _SERVICE,
        "check": "liveness",
        "timestamp": _timestamp(),
    }


@router.get("/health/ready")
def readiness(response: Response) -> dict[str, str | dict[str, str]]:
    db_ready = database_ready()
    sftp_state = _sftp_runtime_state()
    dependencies = {
        "database": "ok" if db_ready else "unavailable",
        "sftp_runtime": sftp_state,
    }

    if not db_ready or sftp_state == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "service": _SERVICE,
            "check": "readiness",
            "timestamp": _timestamp(),
            "dependencies": dependencies,
        }

    return {
        "status": "ready",
        "service": _SERVICE,
        "check": "readiness",
        "timestamp": _timestamp(),
        "dependencies": dependencies,
    }


@router.get("/health")
def health() -> dict[str, str]:
    """Backward-compatible process health endpoint.

    Runtime/orchestrator readiness must use `/health/ready`; this endpoint remains
    a cheap liveness-compatible check for existing callers.
    """
    return {
        "status": "ok",
        "service": _SERVICE,
        "timestamp": _timestamp(),
    }

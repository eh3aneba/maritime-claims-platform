from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db.session import create_session

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
    if not database_ready():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "service": _SERVICE,
            "check": "readiness",
            "timestamp": _timestamp(),
            "dependencies": {"database": "unavailable"},
        }

    return {
        "status": "ready",
        "service": _SERVICE,
        "check": "readiness",
        "timestamp": _timestamp(),
        "dependencies": {"database": "ok"},
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

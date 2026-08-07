from datetime import UTC, datetime

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "maritime-claims-api",
        "timestamp": datetime.now(UTC).isoformat(),
    }

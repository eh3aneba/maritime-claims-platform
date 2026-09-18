from app.modules import ai_runtime
from app.modules.intelligence import router as intelligence_router
from app.modules.processing import service as processing_service


def test_queue_and_worker_share_canonical_external_ai_runtime_selector() -> None:
    """Queue-time and worker-time authorization must use one control-plane selector."""
    assert (
        intelligence_router.require_external_ai_runtime_authorization
        is ai_runtime.require_external_ai_runtime_authorization
    )
    assert (
        processing_service.require_external_ai_runtime_authorization
        is ai_runtime.require_external_ai_runtime_authorization
    )

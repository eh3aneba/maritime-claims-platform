from types import SimpleNamespace
from uuid import uuid4

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


def test_worker_runtime_gate_delegates_to_canonical_selector(monkeypatch) -> None:
    organization_id = uuid4()
    document_id = uuid4()
    requested_by_id = uuid4()
    extraction = SimpleNamespace(char_count=4321)

    class FakeSession:
        def scalar(self, _statement):
            return extraction

    captured = {}

    def canonical_selector(db, **kwargs):
        captured["db"] = db
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        processing_service,
        "get_ai_provider",
        lambda: SimpleNamespace(name="openai"),
    )
    monkeypatch.setattr(
        processing_service,
        "require_external_ai_runtime_authorization",
        canonical_selector,
    )

    db = FakeSession()
    document = SimpleNamespace(
        id=document_id,
        organization_id=organization_id,
    )
    job = SimpleNamespace(requested_by_id=requested_by_id)

    processing_service._require_ai_job_runtime_authorization(
        db,
        job=job,
        document=document,
        expected_document_type="engine_log",
    )

    assert captured == {
        "db": db,
        "organization_id": organization_id,
        "document": document,
        "expected_document_type": "engine_log",
        "input_char_count": 4321,
        "requested_by_id": requested_by_id,
    }

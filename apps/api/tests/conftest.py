from __future__ import annotations

import pytest

from app.modules.documents import service as document_service


@pytest.fixture(autouse=True)
def _align_routable_read_cutover_document_storage(request):
    """Bind live-download storage to the same tmp_path used by the J recovery chain.

    Earlier recovery phases patch only the recovery-service settings because they
    never exercise the ordinary document download path. Phase 17.3-J does. Keep
    this override narrowly scoped to the new routable-cutover test module so the
    production document service remains untouched and the rest of the suite keeps
    its normal storage configuration.
    """
    if request.node.path.name != "test_evidence_recovery_routable_read_cutover.py":
        yield
        return

    monkeypatch = request.getfixturevalue("monkeypatch")
    tmp_path = request.getfixturevalue("tmp_path")
    settings = document_service.settings.model_copy(
        update={"local_storage_path": str(tmp_path)}
    )
    monkeypatch.setattr(document_service, "settings", settings)
    yield

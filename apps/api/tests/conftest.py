from __future__ import annotations

import pytest

from app.modules.documents import service as document_service


@pytest.fixture(autouse=True)
def _align_routable_read_cutover_document_storage(request):
    """Bind live-download storage to the tmp_path used by routable recovery tests.

    Earlier recovery phases patch only recovery-service settings because they do
    not exercise the ordinary document download path. Phases J, M, N, P, Q, R, S, T, U, V and W do.
    Keep this override narrowly scoped to those routable-read test modules so the
    production document service remains untouched and the rest of the suite keeps
    its normal storage configuration.
    """
    if request.node.path.name not in {
        "test_evidence_recovery_routable_read_cutover.py",
        "test_evidence_recovery_durable_read_routing.py",
        "test_evidence_recovery_durable_read_health_qualification.py",
        "test_evidence_recovery_durable_read_renewal_routing.py",
        "test_evidence_recovery_durable_read_renewal_health_qualification.py",
        "test_evidence_recovery_durable_read_renewal_reauthorization.py",
        "test_evidence_recovery_durable_read_reauthorized_renewal_routing.py",
        "test_evidence_recovery_durable_read_reauthorized_renewal_ttl.py",
        "test_evidence_recovery_durable_read_reauthorized_renewal_health_qualification.py",
        "test_evidence_recovery_durable_read_reauthorized_renewal_health_guardrails.py",
        "test_evidence_recovery_read_ownership_transition_authorization.py",
        "test_evidence_recovery_read_ownership_transition_routing.py",
        "test_evidence_recovery_read_ownership_transition_health_qualification.py",
    }:
        yield
        return

    monkeypatch = request.getfixturevalue("monkeypatch")
    tmp_path = request.getfixturevalue("tmp_path")
    settings = document_service.settings.model_copy(
        update={"local_storage_path": str(tmp_path)}
    )
    monkeypatch.setattr(document_service, "settings", settings)
    yield

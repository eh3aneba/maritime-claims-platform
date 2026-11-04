import os
import subprocess
import sys
import textwrap
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.modules.external_document_sources import service
from app.modules.external_document_sources.models import ExternalDocumentSourceProfileReceipt
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_external_document_source_profiles import _headers, _request_sharepoint, _seed_tenant


def setup_function() -> None:
    reset_database()


def _requested_profile(seed: str) -> tuple[UUID, UUID]:
    org, requester, _, _ = _seed_tenant(seed)
    response = _request_sharepoint(_headers(requester))
    assert response.status_code == 201, response.text
    return org, UUID(response.json()["id"])


def test_alternating_profile_and_tenant_parameters_never_reuse_previous_result() -> None:
    first_org, first_id = _requested_profile("query-first")
    second_org, second_id = _requested_profile("query-second")
    with TestingSessionLocal() as db:
        for org, pid, other_org in [(first_org, first_id, second_org), (second_org, second_id, first_org)] * 2:
            row = service.get_external_document_source_profile(db, organization_id=org, profile_id=pid)
            assert row.id == pid and row.organization_id == org
            with pytest.raises(service.ExternalDocumentSourceNotFoundError):
                service.get_external_document_source_profile(db, organization_id=other_org, profile_id=pid)


def test_valid_read_then_flushed_receipt_drift_rejects_and_rollback_recovers() -> None:
    org, pid = _requested_profile("query-receipt-drift")
    with TestingSessionLocal() as db:
        assert service.get_external_document_source_profile(db, organization_id=org, profile_id=pid).id == pid
        receipt = db.scalar(select(ExternalDocumentSourceProfileReceipt).where(
            ExternalDocumentSourceProfileReceipt.organization_id == org,
            ExternalDocumentSourceProfileReceipt.profile_id == pid,
        ))
        assert receipt is not None
        receipt.reason = "Synthetic receipt drift after a previously valid read."
        db.flush()
        try:
            with pytest.raises(service.ExternalDocumentSourceConflictError):
                service.get_external_document_source_profile(db, organization_id=org, profile_id=pid)
        finally:
            db.rollback()
        assert service.get_external_document_source_profile(db, organization_id=org, profile_id=pid).id == pid


def test_profile_lookup_keeps_requested_postgresql_row_lock() -> None:
    # SQL compilation protects the requested lock, not a real concurrency proof.
    org, pid = _requested_profile("query-lock")
    statements = []
    with TestingSessionLocal() as db:
        class CaptureSession:
            def scalar(self, statement, *args, **kwargs):
                statements.append(str(statement.compile(dialect=postgresql.dialect())))
                return db.scalar(statement, *args, **kwargs)
        for locked in [False, True, False]:
            row = service._get_profile(CaptureSession(), organization_id=org, profile_id=pid, for_update=locked)
            assert row.id == pid
    assert ["FOR UPDATE" in sql for sql in statements] == [False, True, False]


def test_pending_profile_drift_is_autoflushed_and_rejected_then_rollback_recovers() -> None:
    org, pid = _requested_profile("query-autoflush")
    with TestingSessionLocal() as db:
        profile = service.get_external_document_source_profile(db, organization_id=org, profile_id=pid)
        profile.request_reason = "Synthetic pending profile drift before another read."
        try:
            with pytest.raises(service.ExternalDocumentSourceConflictError):
                service.get_external_document_source_profile(db, organization_id=org, profile_id=pid)
            assert not db.is_modified(profile)
        finally:
            db.rollback()
        assert service.get_external_document_source_profile(db, organization_id=org, profile_id=pid).id == pid


def test_profile_lookup_after_service_first_import_in_fresh_process() -> None:
    # Foreign-key column types may resolve only after the model registry loads.
    # Exercise the public read with an early service import, not just a warm app.
    code = textwrap.dedent("""\
        from uuid import UUID
        from app.modules.external_document_sources import service
        from tests.db_harness import TestingSessionLocal, reset_database, engine
        from tests.test_external_document_source_profiles import _seed_tenant, _headers, _request_sharepoint
        assert engine.dialect.name == "sqlite" and engine.url.database == ":memory:"
        reset_database()
        org, requester, _, _ = _seed_tenant("early-query-import")
        response = _request_sharepoint(_headers(requester))
        assert response.status_code == 201, response.text
        profile_id = UUID(response.json()["id"])
        with TestingSessionLocal() as db:
            row = service.get_external_document_source_profile(db, organization_id=org, profile_id=profile_id)
            assert row.id == profile_id and row.organization_id == org
    """)
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "MCRI_TEST_DATABASE_URL": "", "AI_PROVIDER": "disabled",
             "EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED": "false",
             "EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED": "false"},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import os
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

import app.modules.external_document_sources.observation_refresh_execution_service as refresh_service
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
    ExternalDocumentSourceObservationRefreshReceipt,
    ExternalDocumentSourceObservationRefreshRecoveryAnchor,
    ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    clear_external_document_source_sftp_file_content_read_adapter,
    register_external_document_source_sftp_file_content_read_adapter,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_remote_content_staging import _QuarantineStore
from tests.test_external_document_source_sftp_file_content_proof import _FileReadAdapter
from tests.test_external_document_source_sftp_observation_refresh_execution import (
    _approved_sftp_refresh,
    setup_function as _ab_setup,
    teardown_function as _ab_teardown,
)


_REASON = (
    "Consume the exact approved changed SFTP file through the durable AE-C crash recovery anchor."
)
_POSTGRES_RECOVERY_GATE = (
    os.environ.get("EXTERNAL_EVIDENCE_REFRESH_EXECUTION_POSTGRES_TEST") == "1"
)


def _skip_heavy_sftp_in_postgres_gate() -> None:
    if _POSTGRES_RECOVERY_GATE:
        pytest.skip(
            "The AE-C PostgreSQL gate uses the focused provider-neutral recovery-anchor "
            "test below; exact SFTP crash recovery remains in Full Backend where the "
            "long production-shaped lineage is sharded with a 40-minute bound."
        )


def setup_function() -> None:
    _ab_setup()
    clear_external_document_source_sftp_file_content_read_adapter()


def teardown_function() -> None:
    clear_external_document_source_sftp_file_content_read_adapter()
    _ab_teardown()


def test_ae_c_object_write_then_final_db_failure_recovers_without_second_provider_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_heavy_sftp_in_postgres_gate()
    (
        _chain,
        _metadata_adapter,
        actor_id,
        organization_id,
        profile_id,
        refresh_authorization_id,
        observed_size,
    ) = _approved_sftp_refresh(monkeypatch, "cw")

    first_adapter = _FileReadAdapter(content=b"c" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(first_adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        real_commit = db.commit
        commit_calls = {"count": 0}

        def _fail_final_commit() -> None:
            commit_calls["count"] += 1
            if commit_calls["count"] == 2:
                raise RuntimeError("simulated-final-db-commit-crash")
            real_commit()

        monkeypatch.setattr(db, "commit", _fail_final_commit)
        with pytest.raises(RuntimeError, match="simulated-final-db-commit-crash"):
            execute_observation_refresh_authorization(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=refresh_authorization_id,
                requested_by_id=actor_id,
                request_key="ae-c-crash-refresh-key",
                request_reason=_REASON,
                now=datetime(2026, 9, 29, 8, 0, tzinfo=UTC),
            )
        assert commit_calls["count"] == 2
        db.rollback()
        monkeypatch.setattr(db, "commit", real_commit)

    assert len(first_adapter.calls) == 1
    assert store.put_calls == 1

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchor).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 0
        assert db.query(ExternalDocumentSourceObservationRefreshReceipt).count() == 0

    # Simulate process/runtime replacement. The replacement adapter must be
    # policy-compatible but must never be called because the anchored object
    # is now the recoverable custody fact.
    replacement_adapter = _FileReadAdapter(content=b"z" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(replacement_adapter)
    with TestingSessionLocal() as db:
        execution, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-crash-refresh-key",
            request_reason=_REASON,
            now=datetime(2026, 9, 29, 8, 1, tzinfo=UTC),
        )
        assert outcome == "completed"
        execution_id = execution.id

    assert len(first_adapter.calls) == 1
    assert len(replacement_adapter.calls) == 0
    assert store.put_calls == 1

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchor).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshReceipt).count() == 1
        persisted = db.get(ExternalDocumentSourceObservationRefreshExecution, execution_id)
        assert persisted is not None
        assert persisted.requested_at == datetime(2026, 9, 29, 8, 0, tzinfo=UTC)


def test_ae_c_anchor_only_restart_performs_one_controlled_provider_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_heavy_sftp_in_postgres_gate()
    (
        _chain,
        _metadata_adapter,
        actor_id,
        organization_id,
        profile_id,
        refresh_authorization_id,
        observed_size,
    ) = _approved_sftp_refresh(monkeypatch, "anchor-only")

    adapter = _FileReadAdapter(content=b"d" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    real_read = refresh_service._read_exact_changed_content

    def _crash_before_provider_read(*_args, **_kwargs):
        raise RuntimeError("simulated-crash-after-anchor-commit")

    monkeypatch.setattr(
        refresh_service,
        "_read_exact_changed_content",
        _crash_before_provider_read,
    )
    with TestingSessionLocal() as db:
        with pytest.raises(RuntimeError, match="simulated-crash-after-anchor-commit"):
            execute_observation_refresh_authorization(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=refresh_authorization_id,
                requested_by_id=actor_id,
                request_key="ae-c-anchor-only-key",
                request_reason=_REASON,
                now=datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
            )
        db.rollback()

    assert len(adapter.calls) == 0
    assert store.put_calls == 0
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchor).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 0

    monkeypatch.setattr(refresh_service, "_read_exact_changed_content", real_read)
    with TestingSessionLocal() as db:
        execution, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-anchor-only-key",
            request_reason=_REASON,
            now=datetime(2026, 9, 29, 9, 1, tzinfo=UTC),
        )
        assert outcome == "completed"
        assert execution.requested_at == datetime(2026, 9, 29, 9, 0, tzinfo=UTC)

    assert len(adapter.calls) == 1
    assert store.put_calls == 1


def test_ae_c_unanchored_preexisting_quarantine_object_fails_closed_before_provider_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_heavy_sftp_in_postgres_gate()
    (
        _chain,
        _metadata_adapter,
        actor_id,
        organization_id,
        profile_id,
        refresh_authorization_id,
        observed_size,
    ) = _approved_sftp_refresh(monkeypatch, "orphan")

    adapter = _FileReadAdapter(content=b"e" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    execution_id = uuid5(
        NAMESPACE_URL,
        f"mcri:observation-refresh:{refresh_authorization_id}",
    )
    storage_key = refresh_service._storage_key(
        refresh_authorization_id,
        execution_id,
    )
    store.objects[storage_key] = b"unproven-orphan"

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="already occupied without durable authority",
        ):
            execute_observation_refresh_authorization(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=refresh_authorization_id,
                requested_by_id=actor_id,
                request_key="ae-c-orphan-key",
                request_reason=_REASON,
                now=datetime(2026, 9, 29, 10, 0, tzinfo=UTC),
            )
        db.rollback()

    assert len(adapter.calls) == 0
    assert store.put_calls == 0
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchor).count() == 0
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt).count() == 0
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 0

@pytest.mark.skipif(
    not _POSTGRES_RECOVERY_GATE,
    reason="Focused recovery state-machine proof is only needed in the AE-C PostgreSQL gate.",
)
def test_ae_c_postgres_gate_recovery_state_machine_avoids_duplicate_sftp_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The PostgreSQL concurrency suite separately proves real row locking and
    # cardinality. This focused AE-C test isolates the crash boundary itself so
    # the gate does not rebuild the entire multi-generation SFTP lineage.
    organization_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:org")
    claim_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:claim")
    profile_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:profile")
    authorization_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:authorization")
    actor_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:actor")
    decision_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:decision")
    handoff_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:handoff")
    observation_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:observation")
    binding_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:binding")
    family_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:family")
    current_document_id = uuid5(NAMESPACE_URL, "mcri:test:ae-c-recovery:document")

    payload = b"ae-c-recovery-sftp-payload"
    digest = hashlib.sha256(payload).hexdigest()
    version_hash = "f" * 64
    current_hash = "0" * 64

    authorization = SimpleNamespace(
        id=authorization_id,
        organization_id=organization_id,
        claim_id=claim_id,
        profile_id=profile_id,
        decision_id=decision_id,
        handoff_id=handoff_id,
        binding_id=binding_id,
        document_family_id=family_id,
        current_document_id=current_document_id,
        current_version_number=1,
        current_document_file_hash=current_hash,
        provider_kind="sftp",
        profile_hash="1" * 64,
        stable_source_item_hash="2" * 64,
        authorization_hash="3" * 64,
        handoff_completion_hash="4" * 64,
        binding_completion_hash="5" * 64,
        observed_projection_hash="6" * 64,
        observed_version_token_hash=version_hash,
    )
    decision = SimpleNamespace(id=decision_id, completion_hash="7" * 64)
    observation = SimpleNamespace(
        id=observation_id,
        completion_hash="8" * 64,
        observed_byte_size=len(payload),
        observed_mime_type_class="application/pdf",
        observed_version_token_hash=version_hash,
    )
    current = SimpleNamespace(
        id=current_document_id,
        version_number=1,
        file_hash=current_hash,
    )
    read_context = refresh_service._RefreshReadContext(
        provider_kind="sftp",
        read_operation_kind="sftp_exact_file_read_v1",
        read_adapter_kind="deterministic_sftp_recovery_test_v1",
        policy_hash="9" * 64,
        adapter=object(),
        target=object(),
        expected_auth_kind="password",
    )

    store = _QuarantineStore()
    read_calls = {"count": 0}

    class _Query:
        def __init__(self, model):
            self.model = model

        def where(self, *_args, **_kwargs):
            return self

        def with_for_update(self):
            return self

    class _Session:
        def __init__(self):
            self.anchor = None
            self.anchor_receipt = None
            self.execution = None
            self.execution_receipt = None
            self.pending = []
            self.commit_calls = 0
            self.fail_final_commit = True

        def scalar(self, query):
            if query.model is ExternalDocumentSourceObservationRefreshExecution:
                return self.execution
            if query.model is ExternalDocumentSourceObservationRefreshRecoveryAnchor:
                return self.anchor
            return None

        def add(self, row):
            self.pending.append(row)

        def flush(self):
            return None

        def commit(self):
            self.commit_calls += 1
            if self.fail_final_commit and self.commit_calls == 2:
                raise RuntimeError("simulated-final-db-commit-crash")
            for row in self.pending:
                if isinstance(row, ExternalDocumentSourceObservationRefreshRecoveryAnchor):
                    self.anchor = row
                elif isinstance(
                    row,
                    ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt,
                ):
                    self.anchor_receipt = row
                elif isinstance(row, ExternalDocumentSourceObservationRefreshExecution):
                    self.execution = row
                elif isinstance(row, ExternalDocumentSourceObservationRefreshReceipt):
                    self.execution_receipt = row
            self.pending.clear()

        def rollback(self):
            self.pending.clear()

        def refresh(self, _row):
            return None

    db = _Session()

    monkeypatch.setattr(refresh_service, "select", lambda model: _Query(model))
    monkeypatch.setattr(refresh_service, "_require_human_admin", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        refresh_service,
        "_authorization_for_update",
        lambda *_args, **_kwargs: authorization,
    )
    monkeypatch.setattr(
        refresh_service,
        "_originating_observation",
        lambda *_args, **_kwargs: (decision, observation),
    )
    monkeypatch.setattr(
        refresh_service,
        "_provider_read_context",
        lambda *_args, **_kwargs: (current, read_context),
    )
    monkeypatch.setattr(refresh_service, "_configured_store", lambda: store)
    monkeypatch.setattr(
        refresh_service,
        "_ensure_recovery_anchor_integrity",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        refresh_service,
        "ensure_observation_refresh_execution_integrity",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(refresh_service, "write_audit_log", lambda *_args, **_kwargs: None)

    def _read_once(_context, _observation):
        read_calls["count"] += 1
        return payload, digest, len(payload), "application/pdf", version_hash

    monkeypatch.setattr(refresh_service, "_read_exact_changed_content", _read_once)

    reason = (
        "Exercise the durable SFTP recovery anchor after object persistence and "
        "before the final completed execution commit."
    )
    requested_at = datetime(2026, 9, 29, 11, 0, tzinfo=UTC)

    with pytest.raises(RuntimeError, match="simulated-final-db-commit-crash"):
        execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-recovery-state-machine",
            request_reason=reason,
            now=requested_at,
        )
    db.rollback()

    assert db.anchor is not None
    assert db.anchor_receipt is not None
    assert db.execution is None
    assert db.execution_receipt is None
    assert read_calls["count"] == 1
    assert store.put_calls == 1

    db.fail_final_commit = False
    execution, outcome = execute_observation_refresh_authorization(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
        requested_by_id=actor_id,
        request_key="ae-c-recovery-state-machine",
        request_reason=reason,
        now=datetime(2026, 9, 29, 11, 1, tzinfo=UTC),
    )

    assert outcome == "completed"
    assert execution is db.execution
    assert db.execution_receipt is not None
    assert read_calls["count"] == 1
    assert store.put_calls == 1
    assert execution.requested_at == requested_at
    assert execution.provider_kind == "sftp"
    assert execution.content_sha256 == digest


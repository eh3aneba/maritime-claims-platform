from __future__ import annotations

from uuid import UUID

import pytest

from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.recurring_observation_provider_lineage import (
    read_recurring_provider_metadata,
    resolve_recurring_provider_lineage,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
)
from tests.db_harness import TestingSessionLocal
from tests.ci_due_tick_stage_timing import ci_due_tick_stage
from tests.test_external_document_source_recurring_observation_schedule import (
    _authorize as _authorize_schedule,
)
from tests.test_external_document_source_sftp_evidence_admission_execution import (
    _authorized_phase_s,
    _enable_clean_admission,
    _execute,
)
from tests.test_external_document_source_sftp_evidence_family_binding import (
    _bind,
    setup_function as _u_setup,
    teardown_function as _u_teardown,
)


def setup_function() -> None:
    _u_setup()


def teardown_function() -> None:
    _u_teardown()


def _bound_sftp(monkeypatch: pytest.MonkeyPatch, seed: str):
    with ci_due_tick_stage("sftp_phase_s_setup"):
        chain, adapter, _r_body, claim_id, authorization = _authorized_phase_s(seed)
    _enable_clean_admission(monkeypatch)
    with ci_due_tick_stage("sftp_phase_t_admit"):
        admitted = _execute(
            chain,
            authorization["id"],
            key=f"{seed}-t-admit",
        )
    assert admitted.status_code == 201, admitted.text
    execution = admitted.json()
    with ci_due_tick_stage("sftp_phase_u_bind"):
        binding = _bind(
            chain,
            execution["id"],
            key=f"{seed}-u-bind",
        )
    assert binding.status_code == 201, binding.text
    return chain, adapter, claim_id, authorization, execution, binding.json()


def test_phase_w_resolves_sftp_u_binding_and_reads_exact_stat_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _claim_id, _authorization, _execution, binding_body = (
        _bound_sftp(monkeypatch, "sftp-phase-w-resolve")
    )

    with TestingSessionLocal() as db:
        binding = db.get(
            ExternalDocumentSourceEvidenceFamilyBinding,
            UUID(binding_body["id"]),
        )
        assert binding is not None
        lineage = resolve_recurring_provider_lineage(db, binding)

        assert lineage.provider_kind == "sftp"
        assert lineage.profile_hash == binding.profile_hash
        assert lineage.stable_source_item_hash == binding.stable_source_item_hash
        assert lineage.legacy_observation_id is None
        assert lineage.legacy_checkpoint_id is None
        assert lineage.sftp_observation_id is not None
        assert lineage.sftp_checkpoint_id is not None
        assert lineage.sftp_request is not None

        provider_calls_before = len(adapter.calls)
        staged_puts_before = chain["p_store"].put_calls
        staged_heads_before = chain["p_store"].head_calls
        staged_gets_before = chain["p_store"].get_calls
        remote_content_reads_before = len(chain["p_read_adapter"].calls)

        observed = read_recurring_provider_metadata(
            lineage,
            baseline_projection_hash=binding.source_projection_hash,
        )

        assert observed.result_status == "unchanged"
        assert observed.observed_projection_hash == binding.source_projection_hash
        assert observed.observed_display_name_hash is not None
        assert observed.observed_version_token_hash is None
        assert observed.observed_mime_type_class is None
        assert observed.observation_adapter_kind == adapter.adapter_kind
        assert len(adapter.calls) == provider_calls_before + 1
        assert chain["p_store"].put_calls == staged_puts_before
        assert chain["p_store"].head_calls == staged_heads_before
        assert chain["p_store"].get_calls == staged_gets_before
        assert len(chain["p_read_adapter"].calls) == remote_content_reads_before

        request = adapter.calls[-1]
        assert request.max_stat_attempts == 1
        assert request.follow_symlinks is False
        assert request.read_only_intent is True


def test_phase_w_sftp_reader_normalizes_changed_and_missing_without_content_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _claim_id, _authorization, _execution, binding_body = (
        _bound_sftp(monkeypatch, "sftp-phase-w-normalize")
    )

    with TestingSessionLocal() as db:
        binding = db.get(
            ExternalDocumentSourceEvidenceFamilyBinding,
            UUID(binding_body["id"]),
        )
        assert binding is not None
        lineage = resolve_recurring_provider_lineage(db, binding)

        reads_before = len(chain["p_read_adapter"].calls)
        gets_before = chain["p_store"].get_calls

        adapter.mode = "changed"
        changed = read_recurring_provider_metadata(
            lineage,
            baseline_projection_hash=binding.source_projection_hash,
        )
        assert changed.result_status == "changed"
        assert changed.observed_projection_hash is not None
        assert changed.observed_projection_hash != binding.source_projection_hash

        adapter.mode = "missing"
        missing = read_recurring_provider_metadata(
            lineage,
            baseline_projection_hash=binding.source_projection_hash,
        )
        assert missing.result_status == "missing"
        assert missing.observed_projection_hash is None
        assert missing.observed_display_name_hash is None
        assert missing.observed_byte_size is None
        assert missing.observed_modified_at is None

        assert len(chain["p_read_adapter"].calls) == reads_before
        assert chain["p_store"].get_calls == gets_before


def test_phase_w_sftp_lineage_tamper_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _chain, _adapter, _claim_id, authorization, _execution, binding_body = (
        _bound_sftp(monkeypatch, "sftp-phase-w-tamper")
    )

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
            UUID(authorization["id"]),
        )
        assert row is not None
        row.authorized_relative_path_hash = "d" * 64
        db.commit()

    with TestingSessionLocal() as db:
        binding = db.get(
            ExternalDocumentSourceEvidenceFamilyBinding,
            UUID(binding_body["id"]),
        )
        assert binding is not None
        with pytest.raises(ExternalDocumentSourceConflictError):
            resolve_recurring_provider_lineage(db, binding)



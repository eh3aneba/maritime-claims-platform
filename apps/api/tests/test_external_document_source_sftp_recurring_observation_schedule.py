from __future__ import annotations

from uuid import UUID

import pytest

from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_discovery import _seed_tenant
from tests.test_external_document_source_recurring_observation_schedule import (
    _authorize,
    _disable,
    _mfa_headers,
    _replace,
)
from tests.test_external_document_source_sftp_recurring_provider_lineage import (
    _bound_sftp,
    setup_function as _w_setup,
    teardown_function as _w_teardown,
)


def setup_function() -> None:
    _w_setup()


def teardown_function() -> None:
    _w_teardown()


def _io_snapshot(chain: dict, adapter) -> dict:
    return {
        "provider_stat_calls": len(adapter.calls),
        "staged_put_calls": chain["p_store"].put_calls,
        "staged_head_calls": chain["p_store"].head_calls,
        "staged_get_calls": chain["p_store"].get_calls,
        "remote_content_reads": len(chain["p_read_adapter"].calls),
    }


def _assert_io_unchanged(before: dict, chain: dict, adapter) -> None:
    assert len(adapter.calls) == before["provider_stat_calls"]
    assert chain["p_store"].put_calls == before["staged_put_calls"]
    assert chain["p_store"].head_calls == before["staged_head_calls"]
    assert chain["p_store"].get_calls == before["staged_get_calls"]
    assert len(chain["p_read_adapter"].calls) == before["remote_content_reads"]


def test_phase_x_sftp_schedule_authorize_replay_replace_disable_is_authority_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _claim_id, _authorization, _execution, binding = _bound_sftp(
        monkeypatch,
        "sftp-phase-x-lifecycle",
    )
    headers = _mfa_headers(chain["requester_id"])
    before = _io_snapshot(chain, adapter)

    authorized = _authorize(
        chain["profile_id"],
        binding["id"],
        chain["requester_id"],
        key="sftp-phase-x-authorize-1",
        cadence="hourly",
        effective_at="2026-09-28T18:00:00Z",
        headers=headers,
    )
    assert authorized.status_code == 201, authorized.text
    first = authorized.json()
    assert first["provider_kind"] == "sftp"
    assert first["status"] == "active"
    assert first["revision_number"] == 1
    assert first["active_binding_guard"] == binding["id"]

    serialized = authorized.text
    for forbidden in (
        "remote_root_path",
        "entry_relative_path",
        "effective_remote_path",
        "hostname",
        "username",
        "reference_name",
        "secret",
        "credential",
    ):
        assert forbidden not in serialized

    replay = _authorize(
        chain["profile_id"],
        binding["id"],
        chain["requester_id"],
        key="sftp-phase-x-authorize-1",
        cadence="hourly",
        effective_at="2026-09-28T18:00:00Z",
        headers=headers,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first["id"]

    duplicate_active = _authorize(
        chain["profile_id"],
        binding["id"],
        chain["requester_id"],
        key="sftp-phase-x-authorize-2",
        cadence="daily",
        headers=headers,
    )
    assert duplicate_active.status_code == 409, duplicate_active.text

    replaced = _replace(
        chain["profile_id"],
        first["id"],
        chain["requester_id"],
        key="sftp-phase-x-replace-2",
        cadence="every_6_hours",
        headers=headers,
    )
    assert replaced.status_code == 201, replaced.text
    second = replaced.json()
    assert second["provider_kind"] == "sftp"
    assert second["revision_number"] == 2
    assert second["prior_schedule_id"] == first["id"]
    assert second["cadence_minutes"] == 360

    disabled = _disable(
        chain["profile_id"],
        second["id"],
        chain["requester_id"],
        key="sftp-phase-x-disable-2",
        headers=headers,
    )
    assert disabled.status_code == 200, disabled.text
    terminal = disabled.json()
    assert terminal["status"] == "disabled"
    assert terminal["active_binding_guard"] is None
    assert terminal["terminal_hash"] is not None

    _assert_io_unchanged(before, chain, adapter)


def test_phase_x_sftp_schedule_cross_tenant_and_tampered_binding_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _claim_id, _authorization, _execution, binding = _bound_sftp(
        monkeypatch,
        "sftp-phase-x-gates",
    )
    before = _io_snapshot(chain, adapter)

    _other_org, other_admin, _other_approver = _seed_tenant("sftp-phase-x-other")
    cross_tenant = _authorize(
        chain["profile_id"],
        binding["id"],
        other_admin,
        key="sftp-phase-x-cross-tenant",
        headers=_mfa_headers(other_admin),
    )
    assert cross_tenant.status_code == 404, cross_tenant.text
    _assert_io_unchanged(before, chain, adapter)

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceEvidenceFamilyBinding,
            UUID(binding["id"]),
        )
        assert row is not None
        row.stable_source_item_hash = "f" * 64
        db.commit()

    tampered = _authorize(
        chain["profile_id"],
        binding["id"],
        chain["requester_id"],
        key="sftp-phase-x-tampered-binding",
        headers=_mfa_headers(chain["requester_id"]),
    )
    assert tampered.status_code == 409, tampered.text
    _assert_io_unchanged(before, chain, adapter)

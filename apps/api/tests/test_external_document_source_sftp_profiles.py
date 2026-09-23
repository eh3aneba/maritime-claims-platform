from uuid import UUID

import pytest

from app.modules.external_document_sources.models import ExternalDocumentSourceProfile
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_profiles import _headers, _seed_tenant


_FINGERPRINT = "SHA256:" + ("A" * 43)


def setup_function() -> None:
    reset_database()


def _request_sftp(headers: dict[str, str], *, config: dict | None = None):
    payload = {
        "hostname": " SFTP.Claims.EXAMPLE.com. ",
        "port": 22,
        "remote_root_path": "/claims//incoming/./",
        "username": " claims-reader ",
        "host_key_fingerprint": _FINGERPRINT,
        "access_mode": "read_only",
    }
    if config:
        payload.update(config)
    return client.post(
        "/api/v1/external-document-sources/profiles",
        headers=headers,
        json={
            "provider_kind": "sftp",
            "display_name": " SFTP Claims Intake ",
            "config": payload,
            "reason": "Govern one pinned read-only SFTP source before any credential or network authority exists.",
        },
    )


def test_sftp_profile_normalizes_replays_and_requires_independent_approval() -> None:
    org_id, requester_id, approver_id, _ = _seed_tenant("sftp-profile")
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)

    requested = _request_sftp(requester_headers)
    assert requested.status_code == 201, requested.text
    body = requested.json()
    profile_id = body["id"]

    assert body["organization_id"] == str(org_id)
    assert body["provider_kind"] == "sftp"
    assert body["status"] == "pending_second_approval"
    assert body["display_name"] == "SFTP Claims Intake"
    assert body["normalized_config"] == {
        "access_mode": "read_only",
        "host_key_fingerprint": _FINGERPRINT,
        "hostname": "sftp.claims.example.com",
        "port": 22,
        "remote_root_path": "/claims/incoming",
        "username": "claims-reader",
    }
    assert len(body["config_hash"]) == 64
    assert len(body["profile_hash"]) == 64

    for field in (
        "credential_stored",
        "oauth_token_exchanged",
        "remote_list_performed",
        "remote_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "subscription_created",
        "sync_executed",
        "evidence_admitted",
        "document_created",
        "claim_mutated",
        "live_connection_authorized",
    ):
        assert body[field] is False

    replay = _request_sftp(
        requester_headers,
        config={
            "hostname": "sftp.claims.example.com",
            "port": "22",
            "remote_root_path": "/claims/incoming",
            "username": "claims-reader",
        },
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == profile_id
    assert replay.json()["config_hash"] == body["config_hash"]

    self_approval = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=requester_headers,
        json={"reason": "Attempt to approve the same SFTP profile without four-eyes separation."},
    )
    assert self_approval.status_code == 409, self_approval.text

    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=approver_headers,
        json={"reason": "Independently approve only the pinned read-only SFTP source profile."},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "active"
    assert approved_body["live_connection_authorized"] is False
    assert approved_body["credential_stored"] is False
    assert approved_body["remote_list_performed"] is False
    assert approved_body["remote_read_performed"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password", "never-store-this"),
        ("private_key", "-----BEGIN PRIVATE KEY-----"),
        ("passphrase", "never-store-this-either"),
    ],
)
def test_sftp_profile_rejects_secret_bearing_or_unknown_fields(field: str, value: str) -> None:
    _, requester_id, _, _ = _seed_tenant(f"sftp-secret-{field}")
    response = _request_sftp(_headers(requester_id), config={field: value})
    assert response.status_code == 422, response.text
    assert "unsupported or secret-like" in response.text.lower()
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceProfile).count() == 0


@pytest.mark.parametrize("port", [0, 65536, "not-a-port", True])
def test_sftp_profile_rejects_invalid_ports(port) -> None:
    _, requester_id, _, _ = _seed_tenant(f"sftp-port-{str(port).lower()}")
    response = _request_sftp(_headers(requester_id), config={"port": port})
    assert response.status_code == 422, response.text
    assert "port" in response.text.lower()


@pytest.mark.parametrize(
    "fingerprint",
    [
        "MD5:00:11:22:33",
        "SHA256:too-short",
        "",
    ],
)
def test_sftp_profile_requires_pinned_sha256_host_key(fingerprint: str) -> None:
    _, requester_id, _, _ = _seed_tenant("sftp-fingerprint-" + str(len(fingerprint)))
    response = _request_sftp(
        _headers(requester_id),
        config={"host_key_fingerprint": fingerprint},
    )
    assert response.status_code == 422, response.text
    assert "host_key_fingerprint" in response.text


@pytest.mark.parametrize(
    "remote_root",
    [
        "claims/incoming",
        "/claims/../secrets",
        "/claims/\x00bad",
    ],
)
def test_sftp_profile_rejects_unsafe_remote_roots(remote_root: str) -> None:
    _, requester_id, _, _ = _seed_tenant("sftp-root-" + str(abs(hash(remote_root))))
    response = _request_sftp(
        _headers(requester_id),
        config={"remote_root_path": remote_root},
    )
    assert response.status_code == 422, response.text
    assert "remote_root_path" in response.text


def test_sftp_profile_is_tenant_isolated() -> None:
    _, requester_id, _, _ = _seed_tenant("sftp-tenant-a")
    _, other_requester_id, _, _ = _seed_tenant("sftp-tenant-b")

    requested = _request_sftp(_headers(requester_id))
    assert requested.status_code == 201, requested.text
    profile_id = UUID(requested.json()["id"])

    hidden = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}",
        headers=_headers(other_requester_id),
    )
    assert hidden.status_code == 404, hidden.text


def test_sftp_profile_rejects_any_write_intent() -> None:
    _, requester_id, _, _ = _seed_tenant("sftp-write-intent")
    response = _request_sftp(
        _headers(requester_id),
        config={"access_mode": "read_write"},
    )
    assert response.status_code == 422, response.text
    assert "read_only" in response.text

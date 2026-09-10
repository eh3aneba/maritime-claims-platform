from pathlib import Path

from tests.db_harness import client, reset_database
from tests.test_evidence_recovery_restore_rehearsal import (
    _fake_s3,
    _headers,
    _seed_tenant,
)
from tests.test_evidence_recovery_routable_read_cutover import (
    _approved_read_path_authorization,
    _prepare_cutover,
)


def setup_function() -> None:
    reset_database()


def test_routable_read_cutover_control_plane_is_hidden_cross_tenant(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            _manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            admin_headers,
            _approver_headers,
            _third_headers,
            _shadow_id,
            authorization_id,
        ) = _approved_read_path_authorization(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="routable-read-tenant-owner",
        )
        prepared = _prepare_cutover(
            claim_id,
            document_id,
            authorization_id,
            admin_headers,
        )
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]

        foreign_root = tmp_path / "foreign"
        (
            _foreign_org_id,
            _foreign_admin_id,
            foreign_manager_id,
            _foreign_claim_id,
            _foreign_document_id,
            _foreign_storage_key,
            _foreign_local_path,
        ) = _seed_tenant(
            slug="routable-read-tenant-foreign",
            storage_root=foreign_root,
        )
        foreign_headers = _headers(foreign_manager_id)

        lease_read = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-cutover-leases/{lease_id}",
            headers=foreign_headers,
        )
        route_read = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-route",
            headers=foreign_headers,
        )
        document_download = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/download",
            headers=foreign_headers,
        )

        assert lease_read.status_code == 404
        assert route_read.status_code == 404
        assert document_download.status_code == 404

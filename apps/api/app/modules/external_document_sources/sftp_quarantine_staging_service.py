from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    ObjectStoragePreconditionFailed,
    S3CompatibleEvidenceStore,
    S3ObjectStoreConfig,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    ExternalDocumentSourceSftpFileContentProof,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadRequest,
    _active_binding_and_profile,
    _effective_remote_path,
    _ensure_integrity as _ensure_file_content_proof_integrity,
    _load_listing_and_entry,
    _validate_adapter_result,
    get_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_quarantine_staging_models import (
    MAX_SFTP_QUARANTINE_BYTES,
    SFTP_QUARANTINE_STORAGE_PURPOSE,
    ExternalDocumentSourceSftpQuarantineStaging,
    ExternalDocumentSourceSftpQuarantineStagingReceipt,
)


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_FALSE_FIELDS = (
    "credential_stored",
    "session_stored",
    "raw_response_stored",
    "remote_content_returned",
    "remote_content_logged",
    "content_parsed",
    "content_extracted",
    "remote_list_performed",
    "remote_stat_performed",
    "remote_write_performed",
    "remote_rename_performed",
    "remote_delete_performed",
    "remote_mkdir_performed",
    "remote_chmod_performed",
    "remote_chown_performed",
    "remote_touch_performed",
    "command_executed",
    "storage_delete_performed",
    "storage_copy_performed",
    "checkpoint_created",
    "evidence_admitted",
    "document_created",
    "processing_enqueued",
    "ai_executed",
    "claim_mutated",
)


class SftpQuarantineStore(Protocol):
    @property
    def sanitized_health_identity(self): ...

    def put_bytes_if_absent(
        self,
        payload: bytes,
        *,
        storage_key: str,
        expected_sha256: str | None = None,
    ): ...

    def head_object(self, *, storage_key: str): ...

    def get_bytes(
        self,
        *,
        storage_key: str,
        expected_sha256: str | None = None,
    ) -> bytes: ...


_STAGING_STORE_OVERRIDE: SftpQuarantineStore | None = None


def register_external_document_source_sftp_quarantine_staging_store(
    store: SftpQuarantineStore,
) -> None:
    for name in ("put_bytes_if_absent", "head_object", "get_bytes"):
        if not callable(getattr(store, name, None)):
            raise ValueError(
                "SFTP quarantine staging store does not implement the governed object-storage contract"
            )
    identity = getattr(store, "sanitized_health_identity", None)
    backend = getattr(identity, "backend", None)
    if not isinstance(backend, str) or not _SAFE_IDENTIFIER.fullmatch(backend):
        raise ValueError("SFTP quarantine staging store backend identity is invalid")
    global _STAGING_STORE_OVERRIDE
    _STAGING_STORE_OVERRIDE = store


def clear_external_document_source_sftp_quarantine_staging_store() -> None:
    global _STAGING_STORE_OVERRIDE
    _STAGING_STORE_OVERRIDE = None


def _configured_store() -> SftpQuarantineStore:
    if _STAGING_STORE_OVERRIDE is not None:
        return _STAGING_STORE_OVERRIDE
    settings = get_settings()
    if not settings.s3_foundation_enabled:
        raise ExternalDocumentSourceConflictError(
            "Governed S3 foundation is not enabled for SFTP quarantine staging"
        )
    config = S3ObjectStoreConfig(
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        bucket=settings.s3_bucket,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        session_token=settings.s3_session_token.get_secret_value(),
        request_timeout_seconds=settings.s3_request_timeout_seconds,
        max_attempts=settings.s3_max_attempts,
        tls_verify=settings.s3_tls_verify,
    )
    try:
        config.validate(
            require_https=settings.app_env.strip().lower() in {"staging", "production"}
        )
        return S3CompatibleEvidenceStore(config)
    except ObjectStorageError:
        raise ExternalDocumentSourceConflictError(
            "Governed S3 foundation configuration is invalid"
        ) from None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _aware(value).isoformat()


def _canonical_hash(value) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(
    value: str,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError(f"{field} must be a string")
    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    if "\x00" in normalized:
        raise ExternalDocumentSourceValidationError(
            f"{field} contains an invalid character"
        )
    return normalized


def _base_safety(executed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "upstream_file_content_proof_completed": True,
        "secret_resolution_performed": executed,
        "provider_network_performed": executed,
        "ssh_transport_performed": executed,
        "host_key_verification_performed": executed,
        "host_key_verified": executed,
        "authentication_performed": executed,
        "authentication_succeeded": executed,
        "sftp_session_opened": executed,
        "sftp_session_closed": executed,
        "remote_content_transiently_observed": executed,
        "remote_read_performed": executed,
        "storage_reconciliation_performed": executed,
        "durable_content_staged": executed,
        "remote_content_stored": executed,
        **{field: False for field in _FALSE_FIELDS},
    }


def _storage_key(
    staging_id: UUID,
    organization_id: UUID,
    digest: str,
) -> str:
    return (
        f"external-sftp-content-quarantine/"
        f"{organization_id}/{staging_id}/{digest}"
    )


def _scope_hash(
    proof: ExternalDocumentSourceSftpFileContentProof,
    *,
    storage_backend_kind: str,
    storage_object_key_hash: str,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(proof.organization_id),
            "profile_id": str(proof.profile_id),
            "file_content_proof_id": str(proof.id),
            "directory_listing_id": str(proof.directory_listing_id),
            "listing_entry_id": str(proof.listing_entry_id),
            "session_activation_id": str(proof.session_activation_id),
            "credential_reference_binding_id": str(
                proof.credential_reference_binding_id
            ),
            "provider_kind": proof.provider_kind,
            "profile_hash": proof.profile_hash,
            "locator_hash": proof.locator_hash,
            "authentication_kind": proof.authentication_kind,
            "reference_backend": proof.reference_backend,
            "destination_hostname": proof.destination_hostname,
            "destination_port": proof.destination_port,
            "pinned_host_key_fingerprint": proof.pinned_host_key_fingerprint,
            "remote_root_path_hash": proof.remote_root_path_hash,
            "upstream_scope_hash": proof.scope_hash,
            "upstream_request_hash": proof.request_hash,
            "upstream_result_hash": proof.result_hash,
            "listing_entry_hash": proof.listing_entry_hash,
            "read_adapter_kind": proof.read_adapter_kind,
            "expected_content_sha256": proof.content_sha256,
            "expected_content_byte_count": proof.content_byte_count,
            "storage_backend_kind": storage_backend_kind,
            "storage_purpose": SFTP_QUARANTINE_STORAGE_PURPOSE,
            "storage_object_key_hash": storage_object_key_hash,
            "request_key": request_key,
        }
    )


def _request_hash(
    row: ExternalDocumentSourceSftpQuarantineStaging,
) -> str:
    return _canonical_hash(
        {
            "staging_id": str(row.id),
            "scope_hash": row.scope_hash,
            "storage_object_key": row.storage_object_key,
            "requested_by_id": str(row.requested_by_id),
            "request_reason": row.request_reason,
            "requested_at": _iso(row.requested_at),
            **_base_safety(False),
        }
    )


def _completion_hash(
    row: ExternalDocumentSourceSftpQuarantineStaging,
) -> str:
    if (
        row.completed_at is None
        or row.result_status != "staged_verified"
        or row.status != "completed"
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP quarantine staging completion facts are incomplete"
        )
    return _canonical_hash(
        {
            "staging_id": str(row.id),
            "scope_hash": row.scope_hash,
            "request_hash": row.request_hash,
            "result_status": row.result_status,
            "expected_content_sha256": row.expected_content_sha256,
            "expected_content_byte_count": row.expected_content_byte_count,
            "storage_backend_kind": row.storage_backend_kind,
            "storage_purpose": row.storage_purpose,
            "storage_object_key_hash": row.storage_object_key_hash,
            "stored_etag": row.stored_etag,
            "completed_at": _iso(row.completed_at),
            **_base_safety(True),
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceSftpQuarantineStagingReceipt,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "staging_id": str(receipt.staging_id),
            "sequence_number": receipt.sequence_number,
            "event_type": receipt.event_type,
            "status_after": receipt.status_after,
            "actor_id": str(receipt.actor_id),
            "occurred_at": _iso(receipt.occurred_at),
            "reason": receipt.reason,
            "scope_hash": receipt.scope_hash,
            "decision_hash": receipt.decision_hash,
            "prior_receipt_hash": receipt.prior_receipt_hash,
            **_base_safety(receipt.event_type == "completed"),
        }
    )


def _receipts(
    db: Session,
    row: ExternalDocumentSourceSftpQuarantineStaging,
):
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpQuarantineStagingReceipt)
            .where(
                ExternalDocumentSourceSftpQuarantineStagingReceipt.organization_id
                == row.organization_id,
                ExternalDocumentSourceSftpQuarantineStagingReceipt.staging_id
                == row.id,
            )
            .order_by(
                ExternalDocumentSourceSftpQuarantineStagingReceipt.sequence_number.asc()
            )
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    row: ExternalDocumentSourceSftpQuarantineStaging,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, row)
    receipt = ExternalDocumentSourceSftpQuarantineStagingReceipt(
        organization_id=row.organization_id,
        staging_id=row.id,
        sequence_number=len(rows) + 1,
        event_type=event_type,
        status_after=row.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=rows[-1].receipt_hash if rows else None,
        receipt_hash="0" * 64,
        **_base_safety(event_type == "completed"),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _get_proof(
    db: Session,
    row: ExternalDocumentSourceSftpQuarantineStaging,
) -> ExternalDocumentSourceSftpFileContentProof:
    proof = db.scalar(
        select(ExternalDocumentSourceSftpFileContentProof).where(
            ExternalDocumentSourceSftpFileContentProof.id
            == row.file_content_proof_id,
            ExternalDocumentSourceSftpFileContentProof.organization_id
            == row.organization_id,
            ExternalDocumentSourceSftpFileContentProof.profile_id
            == row.profile_id,
        )
    )
    if proof is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-I file-content proof lineage is missing"
        )
    return proof


def _verify_storage_object(
    store: SftpQuarantineStore,
    row: ExternalDocumentSourceSftpQuarantineStaging,
):
    try:
        metadata = store.head_object(storage_key=row.storage_object_key)
        if (
            metadata.file_hash.lower() != row.expected_content_sha256
            or metadata.file_size_bytes != row.expected_content_byte_count
        ):
            raise ExternalDocumentSourceConflictError(
                "Quarantine object no longer matches the Phase 17.6-I content proof"
            )
        payload = store.get_bytes(
            storage_key=row.storage_object_key,
            expected_sha256=row.expected_content_sha256,
        )
        if len(payload) != row.expected_content_byte_count:
            raise ExternalDocumentSourceConflictError(
                "Quarantine object byte count no longer matches the Phase 17.6-I content proof"
            )
        del payload
        return metadata
    except ExternalDocumentSourceConflictError:
        raise
    except ObjectStorageNotFound:
        raise
    except (ObjectStorageError, ObjectStorageIntegrityError):
        raise ExternalDocumentSourceConflictError(
            "Governed SFTP quarantine storage verification failed"
        ) from None


def _ensure_anchor_integrity(
    db: Session,
    row: ExternalDocumentSourceSftpQuarantineStaging,
    *,
    verify_storage: bool,
) -> None:
    proof = _get_proof(db, row)
    _ensure_file_content_proof_integrity(db, proof)
    if (
        proof.result_status != "read_verified"
        or not _HEX_64.fullmatch(proof.content_sha256)
        or proof.content_byte_count < 0
        or proof.content_byte_count > MAX_SFTP_QUARANTINE_BYTES
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-I file-content proof is not eligible for quarantine staging"
        )

    if (
        row.directory_listing_id != proof.directory_listing_id
        or row.listing_entry_id != proof.listing_entry_id
        or row.session_activation_id != proof.session_activation_id
        or row.credential_reference_binding_id
        != proof.credential_reference_binding_id
        or row.provider_kind != "sftp"
        or row.profile_hash != proof.profile_hash
        or row.locator_hash != proof.locator_hash
        or row.authentication_kind != proof.authentication_kind
        or row.reference_backend != proof.reference_backend
        or row.destination_hostname != proof.destination_hostname
        or row.destination_port != proof.destination_port
        or row.pinned_host_key_fingerprint
        != proof.pinned_host_key_fingerprint
        or row.remote_root_path_hash != proof.remote_root_path_hash
        or row.upstream_scope_hash != proof.scope_hash
        or row.upstream_request_hash != proof.request_hash
        or row.upstream_result_hash != proof.result_hash
        or row.listing_entry_hash != proof.listing_entry_hash
        or row.read_adapter_kind != proof.read_adapter_kind
        or row.expected_content_sha256 != proof.content_sha256
        or row.expected_content_byte_count != proof.content_byte_count
        or row.storage_purpose != SFTP_QUARANTINE_STORAGE_PURPOSE
        or row.storage_object_key
        != _storage_key(
            row.id,
            row.organization_id,
            row.expected_content_sha256,
        )
        or row.storage_object_key_hash
        != hashlib.sha256(
            row.storage_object_key.encode("utf-8")
        ).hexdigest()
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP quarantine staging upstream/custody lineage drifted"
        )

    expected_scope = _scope_hash(
        proof,
        storage_backend_kind=row.storage_backend_kind,
        storage_object_key_hash=row.storage_object_key_hash,
        request_key=row.request_key,
    )
    if (
        row.scope_hash != expected_scope
        or row.request_hash != _request_hash(row)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP quarantine staging request integrity failed"
        )

    rows = _receipts(db, row)
    if (
        not rows
        or rows[0].event_type != "requested"
        or rows[0].sequence_number != 1
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP quarantine staging requested receipt is missing"
        )
    requested = rows[0]
    if (
        requested.status_after != "requested"
        or requested.actor_id != row.requested_by_id
        or _aware(requested.occurred_at) != _aware(row.requested_at)
        or requested.reason != row.request_reason
        or requested.scope_hash != row.scope_hash
        or requested.decision_hash != row.request_hash
        or requested.prior_receipt_hash is not None
        or requested.receipt_hash != _receipt_hash(requested)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP quarantine staging requested receipt integrity failed"
        )
    for field, expected in _base_safety(False).items():
        if bool(getattr(requested, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP quarantine staging requested receipt safety boundary drifted"
            )

    if row.status == "requested":
        if (
            len(rows) != 1
            or row.result_status is not None
            or row.completed_at is not None
            or row.completion_hash is not None
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP quarantine staging recovery-anchor lifecycle drifted"
            )
        for field, expected in _base_safety(False).items():
            if bool(getattr(row, field)) != expected:
                raise ExternalDocumentSourceConflictError(
                    "SFTP quarantine staging recovery-anchor safety boundary drifted"
                )
        return

    if (
        row.status != "completed"
        or row.result_status != "staged_verified"
        or row.completed_at is None
        or row.completion_hash != _completion_hash(row)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP quarantine staging completion integrity failed"
        )
    for field, expected in _base_safety(True).items():
        if bool(getattr(row, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP quarantine staging completion safety boundary drifted"
            )
    if len(rows) != 2 or rows[1].event_type != "completed":
        raise ExternalDocumentSourceConflictError(
            "SFTP quarantine staging receipt lifecycle is incomplete"
        )
    completed = rows[1]
    if (
        completed.sequence_number != 2
        or completed.status_after != "completed"
        or completed.actor_id != row.requested_by_id
        or _aware(completed.occurred_at) != _aware(row.completed_at)
        or completed.reason != row.request_reason
        or completed.scope_hash != row.scope_hash
        or completed.decision_hash != row.completion_hash
        or completed.prior_receipt_hash != requested.receipt_hash
        or completed.receipt_hash != _receipt_hash(completed)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP quarantine staging completed receipt integrity failed"
        )
    for field, expected in _base_safety(True).items():
        if bool(getattr(completed, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP quarantine staging completed receipt safety boundary drifted"
            )
    if _aware(row.completed_at) < _aware(row.requested_at):
        raise ExternalDocumentSourceConflictError(
            "SFTP quarantine staging timestamps drifted"
        )
    if verify_storage:
        _verify_storage_object(_configured_store(), row)


def _complete_from_storage(
    db: Session,
    row: ExternalDocumentSourceSftpQuarantineStaging,
    *,
    metadata,
    completed_at: datetime,
) -> None:
    row.status = "completed"
    row.result_status = "staged_verified"
    row.stored_etag = metadata.etag
    row.completed_at = completed_at
    row.secret_resolution_performed = True
    row.provider_network_performed = True
    row.ssh_transport_performed = True
    row.host_key_verification_performed = True
    row.host_key_verified = True
    row.authentication_performed = True
    row.authentication_succeeded = True
    row.sftp_session_opened = True
    row.sftp_session_closed = True
    row.remote_content_transiently_observed = True
    row.remote_read_performed = True
    row.storage_reconciliation_performed = True
    row.durable_content_staged = True
    row.remote_content_stored = True
    row.completion_hash = _completion_hash(row)
    _append_receipt(
        db,
        row=row,
        event_type="completed",
        actor_id=row.requested_by_id,
        occurred_at=completed_at,
        decision_hash=row.completion_hash,
    )
    db.flush()
    _ensure_anchor_integrity(db, row, verify_storage=False)


def execute_external_document_source_sftp_quarantine_staging(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    file_content_proof_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(
        request_key,
        field="request_key",
        minimum=1,
        maximum=128,
    )
    normalized_reason = _normalize_text(
        request_reason,
        field="reason",
        minimum=8,
        maximum=2000,
    )
    store = _configured_store()
    backend = getattr(store.sanitized_health_identity, "backend", None)
    if not isinstance(backend, str) or not _SAFE_IDENTIFIER.fullmatch(backend):
        raise ExternalDocumentSourceConflictError(
            "Governed SFTP quarantine storage backend identity is invalid"
        )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpQuarantineStaging).where(
            ExternalDocumentSourceSftpQuarantineStaging.organization_id
            == organization_id,
            ExternalDocumentSourceSftpQuarantineStaging.profile_id
            == profile_id,
            ExternalDocumentSourceSftpQuarantineStaging.file_content_proof_id
            == file_content_proof_id,
        )
    )
    new_anchor = existing is None

    if existing is not None:
        _ensure_anchor_integrity(
            db,
            existing,
            verify_storage=existing.status == "completed",
        )
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay for SFTP quarantine staging"
            )
        if existing.status == "completed":
            return existing, "unchanged"
        row = existing
        proof = _get_proof(db, row)
    else:
        collision = db.scalar(
            select(ExternalDocumentSourceSftpQuarantineStaging).where(
                ExternalDocumentSourceSftpQuarantineStaging.organization_id
                == organization_id,
                ExternalDocumentSourceSftpQuarantineStaging.profile_id
                == profile_id,
                ExternalDocumentSourceSftpQuarantineStaging.request_key
                == normalized_key,
            )
        )
        if collision is not None:
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay for SFTP quarantine staging request_key"
            )

        proof = db.scalar(
            select(ExternalDocumentSourceSftpFileContentProof)
            .where(
                ExternalDocumentSourceSftpFileContentProof.id
                == file_content_proof_id,
                ExternalDocumentSourceSftpFileContentProof.organization_id
                == organization_id,
                ExternalDocumentSourceSftpFileContentProof.profile_id
                == profile_id,
            )
            .with_for_update()
        )
        if proof is None:
            raise ExternalDocumentSourceNotFoundError(
                "Phase 17.6-I SFTP file-content proof not found"
            )
        _ensure_file_content_proof_integrity(db, proof)
        if (
            proof.result_status != "read_verified"
            or proof.content_byte_count > MAX_SFTP_QUARANTINE_BYTES
            or not _HEX_64.fullmatch(proof.content_sha256)
        ):
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-I SFTP file-content proof is not eligible for quarantine staging"
            )

        requested_at = _aware(now or _utc_now())
        staging_id = uuid4()
        storage_key = _storage_key(
            staging_id,
            organization_id,
            proof.content_sha256,
        )
        storage_key_hash = hashlib.sha256(
            storage_key.encode("utf-8")
        ).hexdigest()
        scope_hash = _scope_hash(
            proof,
            storage_backend_kind=backend,
            storage_object_key_hash=storage_key_hash,
            request_key=normalized_key,
        )

        row = ExternalDocumentSourceSftpQuarantineStaging(
            id=staging_id,
            organization_id=organization_id,
            profile_id=profile_id,
            file_content_proof_id=proof.id,
            directory_listing_id=proof.directory_listing_id,
            listing_entry_id=proof.listing_entry_id,
            session_activation_id=proof.session_activation_id,
            credential_reference_binding_id=proof.credential_reference_binding_id,
            provider_kind="sftp",
            profile_hash=proof.profile_hash,
            locator_hash=proof.locator_hash,
            authentication_kind=proof.authentication_kind,
            reference_backend=proof.reference_backend,
            destination_hostname=proof.destination_hostname,
            destination_port=proof.destination_port,
            pinned_host_key_fingerprint=proof.pinned_host_key_fingerprint,
            remote_root_path_hash=proof.remote_root_path_hash,
            upstream_scope_hash=proof.scope_hash,
            upstream_request_hash=proof.request_hash,
            upstream_result_hash=proof.result_hash,
            listing_entry_hash=proof.listing_entry_hash,
            read_adapter_kind=proof.read_adapter_kind,
            expected_content_sha256=proof.content_sha256,
            expected_content_byte_count=proof.content_byte_count,
            storage_backend_kind=backend,
            storage_purpose=SFTP_QUARANTINE_STORAGE_PURPOSE,
            storage_object_key=storage_key,
            storage_object_key_hash=storage_key_hash,
            stored_etag=None,
            request_key=normalized_key,
            scope_hash=scope_hash,
            request_hash="0" * 64,
            status="requested",
            result_status=None,
            requested_by_id=requested_by_id,
            request_reason=normalized_reason,
            requested_at=requested_at,
            completed_at=None,
            completion_hash=None,
            **_base_safety(False),
        )
        row.request_hash = _request_hash(row)
        db.add(row)
        db.flush()
        _append_receipt(
            db,
            row=row,
            event_type="requested",
            actor_id=requested_by_id,
            occurred_at=requested_at,
            decision_hash=row.request_hash,
        )
        _ensure_anchor_integrity(db, row, verify_storage=False)

        # Crash-safe recovery authority must survive later reread/storage failures.
        db.commit()
        db.refresh(row)

    if not new_anchor:
        try:
            metadata = _verify_storage_object(store, row)
        except ObjectStorageNotFound:
            metadata = None
        if metadata is not None:
            completed_at = max(_aware(row.requested_at), _utc_now())
            _complete_from_storage(
                db,
                row,
                metadata=metadata,
                completed_at=completed_at,
            )
            return row, "completed"

    listing, entry = _load_listing_and_entry(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        listing_id=proof.directory_listing_id,
        entry_id=proof.listing_entry_id,
        for_update=False,
    )
    binding, normalized_config = _active_binding_and_profile(db, listing)
    adapter = get_external_document_source_sftp_file_content_read_adapter()
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP file content read adapter is unavailable for Phase 17.6-J staging"
        )
    if getattr(adapter, "adapter_kind", None) != proof.read_adapter_kind:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-J SFTP reread adapter drifted from Phase 17.6-I"
        )

    request = SftpFileContentReadRequest(
        hostname=listing.destination_hostname,
        port=listing.destination_port,
        username=normalized_config["username"],
        pinned_host_key_fingerprint=listing.pinned_host_key_fingerprint,
        authentication_kind=binding.authentication_kind,
        reference_backend=binding.reference_backend,
        reference_namespace=binding.reference_namespace,
        reference_name=binding.reference_name,
        reference_version=binding.reference_version,
        remote_root_path=normalized_config["remote_root_path"],
        entry_relative_path=entry.relative_path,
        effective_remote_path=_effective_remote_path(
            normalized_config["remote_root_path"],
            entry.relative_path,
        ),
    )

    payload: bytes | None = None
    try:
        transient_result = adapter.read_content(request)
    except Exception:
        raise ExternalDocumentSourceConflictError(
            "SFTP quarantine staging reread failed"
        ) from None

    try:
        payload, authentication_method, _latency_class = _validate_adapter_result(
            transient_result,
            expected_auth_kind=binding.authentication_kind,
            declared_byte_size=entry.byte_size,
        )
        digest = hashlib.sha256(payload).hexdigest()
        byte_count = len(payload)
        if (
            digest != proof.content_sha256
            or byte_count != proof.content_byte_count
        ):
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-J reread does not match the Phase 17.6-I content proof"
            )
        if authentication_method != proof.authentication_method:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-J authentication method drifted from Phase 17.6-I"
            )
        try:
            store.put_bytes_if_absent(
                payload,
                storage_key=row.storage_object_key,
                expected_sha256=proof.content_sha256,
            )
        except ObjectStoragePreconditionFailed:
            pass
        except ObjectStorageError:
            raise ExternalDocumentSourceConflictError(
                "Governed SFTP quarantine storage write failed"
            ) from None
    finally:
        if payload is not None:
            del payload
        try:
            del transient_result
        except UnboundLocalError:
            pass

    metadata = _verify_storage_object(store, row)
    completed_at = max(_aware(row.requested_at), _utc_now())
    _complete_from_storage(
        db,
        row,
        metadata=metadata,
        completed_at=completed_at,
    )
    return row, "completed"


def get_external_document_source_sftp_quarantine_staging(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    staging_id: UUID,
):
    row = db.scalar(
        select(ExternalDocumentSourceSftpQuarantineStaging).where(
            ExternalDocumentSourceSftpQuarantineStaging.id == staging_id,
            ExternalDocumentSourceSftpQuarantineStaging.organization_id
            == organization_id,
            ExternalDocumentSourceSftpQuarantineStaging.profile_id
            == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP quarantine staging execution not found"
        )
    _ensure_anchor_integrity(
        db,
        row,
        verify_storage=row.status == "completed",
    )
    return row


def list_external_document_source_sftp_quarantine_staging_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    staging_id: UUID,
):
    row = get_external_document_source_sftp_quarantine_staging(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        staging_id=staging_id,
    )
    return _receipts(db, row)

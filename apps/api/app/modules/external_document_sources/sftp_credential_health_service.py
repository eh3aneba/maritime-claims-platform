from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_credential_health_models import (
    ExternalDocumentSourceSftpCredentialHealthQualification,
    ExternalDocumentSourceSftpCredentialHealthReceipt,
)
from app.modules.external_document_sources.sftp_credential_reference_models import (
    ExternalDocumentSourceSftpCredentialReferenceBinding,
)
from app.modules.external_document_sources.sftp_credential_reference_service import (
    get_external_document_source_sftp_credential_reference,
)


_ALLOWED_BACKENDS = {
    "aws_secrets_manager",
    "azure_key_vault",
    "gcp_secret_manager",
    "hashicorp_vault",
}
_ALLOWED_MATERIAL_KINDS = {"password", "private_key"}
_ALLOWED_FAILURE_CODES = {
    "reference_not_found",
    "reference_unresolved",
    "permission_denied",
    "backend_unavailable",
    "resolver_rejected",
    "material_missing",
    "material_invalid",
    "authentication_kind_mismatch",
}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_NON_SECRET_SAFETY_FIELDS = (
    "credential_stored",
    "provider_network_performed",
    "authentication_performed",
    "sftp_session_opened",
    "remote_list_performed",
    "remote_read_performed",
    "remote_write_performed",
    "remote_delete_performed",
    "evidence_admitted",
    "document_created",
    "processing_enqueued",
    "ai_executed",
    "claim_mutated",
)


@dataclass(frozen=True)
class SftpCredentialReferenceLocator:
    backend: str
    namespace: str
    name: str
    version: str | None
    authentication_kind: str


@dataclass(frozen=True)
class SftpCredentialHealthProbeResult:
    resolved: bool
    material_kind: str | None = None
    failure_code: str | None = None


class SftpCredentialHealthResolver(Protocol):
    resolver_kind: str

    def check(
        self,
        locator: SftpCredentialReferenceLocator,
    ) -> SftpCredentialHealthProbeResult: ...


_RESOLVERS: dict[str, SftpCredentialHealthResolver] = {}


def register_external_document_source_sftp_credential_health_resolver(
    backend: str,
    resolver: SftpCredentialHealthResolver,
) -> None:
    normalized_backend = backend.strip().lower()
    if normalized_backend not in _ALLOWED_BACKENDS:
        raise ValueError("Unsupported SFTP credential reference backend")
    resolver_kind = getattr(resolver, "resolver_kind", None)
    if not isinstance(resolver_kind, str) or not _SAFE_IDENTIFIER.fullmatch(
        resolver_kind
    ):
        raise ValueError("SFTP credential health resolver kind is invalid")
    _RESOLVERS[normalized_backend] = resolver


def clear_external_document_source_sftp_credential_health_resolvers() -> None:
    _RESOLVERS.clear()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value).isoformat()


def _canonical_hash(value) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(
    value: str,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> str:
    normalized = value.strip()
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    return normalized


def _normalize_resolver_kind(value: str) -> str:
    normalized = value.strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential health resolver kind is invalid"
        )
    return normalized


def _validate_probe_result(
    result: SftpCredentialHealthProbeResult,
    *,
    expected_material_kind: str,
) -> tuple[str, str | None, str | None]:
    if not isinstance(result, SftpCredentialHealthProbeResult):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential resolver returned an invalid health result"
        )

    if not result.resolved:
        if result.material_kind is not None:
            raise ExternalDocumentSourceConflictError(
                "Unresolved SFTP credential result cannot include material kind"
            )
        if result.failure_code not in _ALLOWED_FAILURE_CODES - {
            "authentication_kind_mismatch"
        }:
            raise ExternalDocumentSourceConflictError(
                "SFTP credential resolver returned an unsupported failure code"
            )
        return "unqualified", result.failure_code, None

    if result.failure_code is not None:
        raise ExternalDocumentSourceConflictError(
            "Resolved SFTP credential result cannot include a failure code"
        )
    if result.material_kind not in _ALLOWED_MATERIAL_KINDS:
        raise ExternalDocumentSourceConflictError(
            "SFTP credential resolver returned an invalid material kind"
        )
    if result.material_kind != expected_material_kind:
        return (
            "unqualified",
            "authentication_kind_mismatch",
            result.material_kind,
        )
    return "qualified", None, result.material_kind


def _scope_hash(*, binding, resolver_kind: str, request_key: str) -> str:
    if binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference approval lineage is incomplete"
        )
    return _canonical_hash(
        {
            "organization_id": str(binding.organization_id),
            "profile_id": str(binding.profile_id),
            "provider_kind": "sftp",
            "profile_hash": binding.profile_hash,
            "credential_reference_binding_id": str(binding.id),
            "binding_scope_hash": binding.scope_hash,
            "binding_request_hash": binding.request_hash,
            "binding_approval_hash": binding.approval_hash,
            "locator_hash": binding.locator_hash,
            "authentication_kind": binding.authentication_kind,
            "reference_backend": binding.reference_backend,
            "resolver_kind": resolver_kind,
            "request_key": request_key,
        }
    )


def _request_hash(
    row: ExternalDocumentSourceSftpCredentialHealthQualification,
) -> str:
    return _canonical_hash(
        {
            "qualification_id": str(row.id),
            "scope_hash": row.scope_hash,
            "requested_by_id": str(row.requested_by_id),
            "request_reason": row.request_reason,
            "requested_at": _iso(row.requested_at),
            "credential_reference_stored": True,
            "secret_resolution_performed": False,
            **{field: False for field in _NON_SECRET_SAFETY_FIELDS},
        }
    )


def _result_hash(
    row: ExternalDocumentSourceSftpCredentialHealthQualification,
) -> str:
    return _canonical_hash(
        {
            "qualification_id": str(row.id),
            "scope_hash": row.scope_hash,
            "request_hash": row.request_hash,
            "checked_at": _iso(row.checked_at),
            "result_status": row.result_status,
            "failure_code": row.failure_code,
            "resolved_material_kind": row.resolved_material_kind,
            "credential_reference_stored": True,
            "secret_resolution_performed": True,
            **{field: False for field in _NON_SECRET_SAFETY_FIELDS},
        }
    )


def _receipt_hash(
    receipt: ExternalDocumentSourceSftpCredentialHealthReceipt,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "qualification_id": str(receipt.qualification_id),
            "sequence_number": receipt.sequence_number,
            "event_type": receipt.event_type,
            "status_after": receipt.status_after,
            "actor_id": str(receipt.actor_id),
            "occurred_at": _iso(receipt.occurred_at),
            "reason": receipt.reason,
            "scope_hash": receipt.scope_hash,
            "decision_hash": receipt.decision_hash,
            "prior_receipt_hash": receipt.prior_receipt_hash,
            "credential_reference_stored": True,
            "secret_resolution_performed": receipt.secret_resolution_performed,
            **{field: False for field in _NON_SECRET_SAFETY_FIELDS},
        }
    )


def _get_qualification(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    qualification_id: UUID,
) -> ExternalDocumentSourceSftpCredentialHealthQualification:
    row = db.scalar(
        select(ExternalDocumentSourceSftpCredentialHealthQualification).where(
            ExternalDocumentSourceSftpCredentialHealthQualification.id
            == qualification_id,
            ExternalDocumentSourceSftpCredentialHealthQualification.organization_id
            == organization_id,
            ExternalDocumentSourceSftpCredentialHealthQualification.profile_id
            == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP credential health qualification not found"
        )
    return row


def _receipts(
    db: Session,
    row: ExternalDocumentSourceSftpCredentialHealthQualification,
) -> list[ExternalDocumentSourceSftpCredentialHealthReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpCredentialHealthReceipt)
            .where(
                ExternalDocumentSourceSftpCredentialHealthReceipt.organization_id
                == row.organization_id,
                ExternalDocumentSourceSftpCredentialHealthReceipt.qualification_id
                == row.id,
            )
            .order_by(
                ExternalDocumentSourceSftpCredentialHealthReceipt.sequence_number.asc()
            )
        ).all()
    )


def _active_binding(
    db: Session,
    row: ExternalDocumentSourceSftpCredentialHealthQualification,
):
    binding = get_external_document_source_sftp_credential_reference(
        db,
        organization_id=row.organization_id,
        profile_id=row.profile_id,
        binding_id=row.credential_reference_binding_id,
    )
    if binding.status != "active" or binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError(
            "Bound SFTP credential reference is not active"
        )
    if (
        row.provider_kind != "sftp"
        or row.profile_hash != binding.profile_hash
        or row.binding_scope_hash != binding.scope_hash
        or row.binding_request_hash != binding.request_hash
        or row.binding_approval_hash != binding.approval_hash
        or row.locator_hash != binding.locator_hash
        or row.authentication_kind != binding.authentication_kind
        or row.reference_backend != binding.reference_backend
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential health upstream lineage drifted"
        )
    return binding


def _lock_active_binding(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
):
    locked = db.scalar(
        select(ExternalDocumentSourceSftpCredentialReferenceBinding)
        .where(
            ExternalDocumentSourceSftpCredentialReferenceBinding.id == binding_id,
            ExternalDocumentSourceSftpCredentialReferenceBinding.organization_id
            == organization_id,
            ExternalDocumentSourceSftpCredentialReferenceBinding.profile_id
            == profile_id,
        )
        .with_for_update()
    )
    if locked is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP credential reference binding not found"
        )
    binding = get_external_document_source_sftp_credential_reference(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    if binding.status != "active" or binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError(
            "Only an active SFTP credential reference may be health-qualified"
        )
    return binding


def _ensure_integrity(
    db: Session,
    row: ExternalDocumentSourceSftpCredentialHealthQualification,
) -> None:
    binding = _active_binding(db, row)

    expected_scope = _scope_hash(
        binding=binding,
        resolver_kind=row.resolver_kind,
        request_key=row.request_key,
    )
    if row.scope_hash != expected_scope or row.request_hash != _request_hash(row):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential health request integrity failed"
        )
    if row.result_hash != _result_hash(row):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential health result integrity failed"
        )
    if (
        not row.credential_reference_stored
        or not row.secret_resolution_performed
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential health resolution boundary drifted"
        )
    if any(
        bool(getattr(row, field))
        for field in _NON_SECRET_SAFETY_FIELDS
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential health safety boundary drifted"
        )

    if row.result_status == "qualified":
        if (
            row.failure_code is not None
            or row.resolved_material_kind != row.authentication_kind
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP credential health qualified result drifted"
            )
    elif row.result_status == "unqualified":
        if row.failure_code not in _ALLOWED_FAILURE_CODES:
            raise ExternalDocumentSourceConflictError(
                "SFTP credential health failure code drifted"
            )
        if (
            row.resolved_material_kind is not None
            and row.resolved_material_kind not in _ALLOWED_MATERIAL_KINDS
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP credential health material kind drifted"
            )
        if (
            row.failure_code == "authentication_kind_mismatch"
            and row.resolved_material_kind == row.authentication_kind
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP credential health mismatch facts drifted"
            )
    else:
        raise ExternalDocumentSourceConflictError(
            "SFTP credential health result status is invalid"
        )

    if _aware(row.checked_at) < _aware(row.requested_at):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential health timestamps drifted"
        )

    receipts = _receipts(db, row)
    if len(receipts) != 2 or [
        receipt.event_type for receipt in receipts
    ] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError(
            "SFTP credential health receipt lifecycle is incomplete"
        )

    expected = (
        (
            1,
            "requested",
            row.requested_at,
            "requested",
            row.request_hash,
            False,
        ),
        (
            2,
            "completed",
            row.checked_at,
            row.result_status,
            row.result_hash,
            True,
        ),
    )
    prior: str | None = None
    for receipt, facts in zip(receipts, expected, strict=True):
        (
            sequence_number,
            event_type,
            occurred_at,
            status_after,
            decision_hash,
            resolution_performed,
        ) = facts
        if (
            receipt.sequence_number != sequence_number
            or receipt.event_type != event_type
            or receipt.actor_id != row.requested_by_id
            or _aware(receipt.occurred_at) != _aware(occurred_at)
            or receipt.reason != row.request_reason
            or receipt.status_after != status_after
            or receipt.scope_hash != row.scope_hash
            or receipt.decision_hash != decision_hash
            or receipt.prior_receipt_hash != prior
            or not receipt.credential_reference_stored
            or receipt.secret_resolution_performed != resolution_performed
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP credential health receipt facts drifted"
            )
        if any(
            bool(getattr(receipt, field))
            for field in _NON_SECRET_SAFETY_FIELDS
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP credential health receipt safety boundary drifted"
            )
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError(
                "SFTP credential health receipt integrity failed"
            )
        prior = receipt.receipt_hash


def _append_receipt(
    db: Session,
    *,
    row: ExternalDocumentSourceSftpCredentialHealthQualification,
    event_type: str,
    status_after: str,
    occurred_at: datetime,
    decision_hash: str,
    resolution_performed: bool,
) -> None:
    receipts = _receipts(db, row)
    receipt = ExternalDocumentSourceSftpCredentialHealthReceipt(
        organization_id=row.organization_id,
        qualification_id=row.id,
        sequence_number=len(receipts) + 1,
        event_type=event_type,
        status_after=status_after,
        actor_id=row.requested_by_id,
        occurred_at=occurred_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=receipts[-1].receipt_hash if receipts else None,
        credential_reference_stored=True,
        secret_resolution_performed=resolution_performed,
        **{field: False for field in _NON_SECRET_SAFETY_FIELDS},
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def qualify_external_document_source_sftp_credential_health(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
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

    binding = _lock_active_binding(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpCredentialHealthQualification).where(
            ExternalDocumentSourceSftpCredentialHealthQualification.credential_reference_binding_id
            == binding_id
        )
    )
    if existing is not None:
        if (
            existing.organization_id != organization_id
            or existing.profile_id != profile_id
        ):
            raise ExternalDocumentSourceNotFoundError(
                "SFTP credential reference binding not found"
            )
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay for SFTP credential health qualification"
            )
        return existing, "unchanged"

    collision = db.scalar(
        select(ExternalDocumentSourceSftpCredentialHealthQualification).where(
            ExternalDocumentSourceSftpCredentialHealthQualification.organization_id
            == organization_id,
            ExternalDocumentSourceSftpCredentialHealthQualification.profile_id
            == profile_id,
            ExternalDocumentSourceSftpCredentialHealthQualification.request_key
            == normalized_key,
        )
    )
    if collision is not None:
        raise ExternalDocumentSourceConflictError(
            "Conflicting replay for SFTP credential health request_key"
        )

    resolver = _RESOLVERS.get(binding.reference_backend)
    if resolver is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference resolver is unavailable"
        )
    resolver_kind = _normalize_resolver_kind(resolver.resolver_kind)

    requested_at = _aware(now or _utc_now())
    locator = SftpCredentialReferenceLocator(
        backend=binding.reference_backend,
        namespace=binding.reference_namespace,
        name=binding.reference_name,
        version=binding.reference_version,
        authentication_kind=binding.authentication_kind,
    )
    try:
        probe = resolver.check(locator)
    except Exception:
        probe = SftpCredentialHealthProbeResult(
            resolved=False,
            failure_code="resolver_rejected",
        )

    (
        result_status,
        failure_code,
        resolved_material_kind,
    ) = _validate_probe_result(
        probe,
        expected_material_kind=binding.authentication_kind,
    )
    checked_at = max(requested_at, _utc_now())
    scope_hash = _scope_hash(
        binding=binding,
        resolver_kind=resolver_kind,
        request_key=normalized_key,
    )

    row = ExternalDocumentSourceSftpCredentialHealthQualification(
        organization_id=organization_id,
        profile_id=profile_id,
        credential_reference_binding_id=binding.id,
        provider_kind="sftp",
        profile_hash=binding.profile_hash,
        binding_scope_hash=binding.scope_hash,
        binding_request_hash=binding.request_hash,
        binding_approval_hash=binding.approval_hash,
        locator_hash=binding.locator_hash,
        authentication_kind=binding.authentication_kind,
        reference_backend=binding.reference_backend,
        resolver_kind=resolver_kind,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=requested_at,
        checked_at=checked_at,
        result_status=result_status,
        failure_code=failure_code,
        resolved_material_kind=resolved_material_kind,
        result_hash="0" * 64,
        credential_reference_stored=True,
        secret_resolution_performed=True,
        **{field: False for field in _NON_SECRET_SAFETY_FIELDS},
    )
    db.add(row)
    db.flush()

    row.request_hash = _request_hash(row)
    row.result_hash = _result_hash(row)

    _append_receipt(
        db,
        row=row,
        event_type="requested",
        status_after="requested",
        occurred_at=requested_at,
        decision_hash=row.request_hash,
        resolution_performed=False,
    )
    _append_receipt(
        db,
        row=row,
        event_type="completed",
        status_after=row.result_status,
        occurred_at=checked_at,
        decision_hash=row.result_hash,
        resolution_performed=True,
    )
    db.flush()
    _ensure_integrity(db, row)
    return row, "completed"


def get_external_document_source_sftp_credential_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    qualification_id: UUID,
):
    row = _get_qualification(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        qualification_id=qualification_id,
    )
    _ensure_integrity(db, row)
    return row


def list_external_document_source_sftp_credential_health_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    qualification_id: UUID,
):
    row = get_external_document_source_sftp_credential_health_qualification(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        qualification_id=qualification_id,
    )
    return _receipts(db, row)

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.credential_reference_service import (
    _normalize_backend,
    _normalize_locator_component,
)
from app.modules.external_document_sources.models import ExternalDocumentSourceProfile
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    get_external_document_source_profile,
)
from app.modules.external_document_sources.sftp_credential_reference_models import (
    ExternalDocumentSourceSftpCredentialReferenceBinding,
    ExternalDocumentSourceSftpCredentialReferenceReceipt,
)


_SAFETY_FIELDS = (
    "credential_stored",
    "secret_resolution_performed",
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
_ALLOWED_AUTHENTICATION_KINDS = {"password", "private_key"}


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
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    normalized = value.strip()
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    return normalized


def _normalize_authentication_kind(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in _ALLOWED_AUTHENTICATION_KINDS:
        raise ExternalDocumentSourceValidationError(
            "Unsupported SFTP authentication kind"
        )
    return normalized


def _locator_hash(
    *,
    authentication_kind: str,
    backend: str,
    namespace: str,
    name: str,
    version: str | None,
) -> str:
    return _canonical_hash(
        {
            "authentication_kind": authentication_kind,
            "reference_backend": backend,
            "reference_namespace": namespace,
            "reference_name": name,
            "reference_version": version,
        }
    )


def _scope_hash(
    *,
    organization_id: UUID,
    profile: ExternalDocumentSourceProfile,
    authentication_kind: str,
    locator_hash: str,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(organization_id),
            "profile_id": str(profile.id),
            "provider_kind": "sftp",
            "profile_hash": profile.profile_hash,
            "authentication_kind": authentication_kind,
            "locator_hash": locator_hash,
            "request_key": request_key,
        }
    )


def _request_hash(binding: ExternalDocumentSourceSftpCredentialReferenceBinding) -> str:
    return _canonical_hash(
        {
            "binding_id": str(binding.id),
            "scope_hash": binding.scope_hash,
            "requested_by_id": str(binding.requested_by_id),
            "request_reason": binding.request_reason,
            "requested_at": _iso(binding.requested_at),
            "credential_reference_stored": True,
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _approval_hash(binding: ExternalDocumentSourceSftpCredentialReferenceBinding) -> str:
    if (
        binding.approved_by_id is None
        or binding.approved_at is None
        or binding.approval_reason is None
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference approval facts are incomplete"
        )
    return _canonical_hash(
        {
            "binding_id": str(binding.id),
            "scope_hash": binding.scope_hash,
            "request_hash": binding.request_hash,
            "approved_by_id": str(binding.approved_by_id),
            "approved_at": _iso(binding.approved_at),
            "approval_reason": binding.approval_reason,
            "status": "active",
            "credential_reference_stored": True,
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _terminal_hash(binding: ExternalDocumentSourceSftpCredentialReferenceBinding) -> str:
    if (
        binding.terminal_by_id is None
        or binding.terminal_at is None
        or binding.terminal_reason is None
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference terminal facts are incomplete"
        )
    return _canonical_hash(
        {
            "binding_id": str(binding.id),
            "scope_hash": binding.scope_hash,
            "request_hash": binding.request_hash,
            "approval_hash": binding.approval_hash,
            "status": binding.status,
            "terminal_by_id": str(binding.terminal_by_id),
            "terminal_at": _iso(binding.terminal_at),
            "terminal_reason": binding.terminal_reason,
            "credential_reference_stored": True,
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceSftpCredentialReferenceReceipt) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "binding_id": str(receipt.binding_id),
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
            **{field: False for field in _SAFETY_FIELDS},
        }
    )


def _get_binding(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
) -> ExternalDocumentSourceSftpCredentialReferenceBinding:
    binding = db.scalar(
        select(ExternalDocumentSourceSftpCredentialReferenceBinding).where(
            ExternalDocumentSourceSftpCredentialReferenceBinding.id == binding_id,
            ExternalDocumentSourceSftpCredentialReferenceBinding.organization_id
            == organization_id,
            ExternalDocumentSourceSftpCredentialReferenceBinding.profile_id == profile_id,
        )
    )
    if binding is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP credential reference binding not found"
        )
    return binding


def _receipts(
    db: Session,
    binding: ExternalDocumentSourceSftpCredentialReferenceBinding,
) -> list[ExternalDocumentSourceSftpCredentialReferenceReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpCredentialReferenceReceipt)
            .where(
                ExternalDocumentSourceSftpCredentialReferenceReceipt.organization_id
                == binding.organization_id,
                ExternalDocumentSourceSftpCredentialReferenceReceipt.binding_id
                == binding.id,
            )
            .order_by(
                ExternalDocumentSourceSftpCredentialReferenceReceipt.sequence_number.asc()
            )
        ).all()
    )


def _profile_for_binding(
    db: Session,
    binding: ExternalDocumentSourceSftpCredentialReferenceBinding,
) -> ExternalDocumentSourceProfile:
    profile = get_external_document_source_profile(
        db,
        organization_id=binding.organization_id,
        profile_id=binding.profile_id,
    )
    if (
        profile.provider_kind != "sftp"
        or binding.provider_kind != "sftp"
        or binding.profile_hash != profile.profile_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference profile lineage drifted"
        )
    return profile


def _require_active_sftp_profile(profile: ExternalDocumentSourceProfile) -> None:
    if profile.provider_kind != "sftp":
        raise ExternalDocumentSourceConflictError(
            "Credential reference custody requires an SFTP source profile"
        )
    if profile.status != "active":
        raise ExternalDocumentSourceConflictError(
            "Bound SFTP source profile is not active"
        )


def _expected_events(
    binding: ExternalDocumentSourceSftpCredentialReferenceBinding,
) -> list[str]:
    if binding.status == "pending_second_approval":
        return ["requested"]
    if binding.status == "active":
        return ["requested", "approved"]
    if binding.status == "rejected":
        return ["requested", "rejected"]
    if binding.status == "disabled":
        return ["requested", "approved", "disabled"]
    raise ExternalDocumentSourceConflictError(
        "SFTP credential reference status is invalid"
    )


def _expected_receipt_facts(
    binding: ExternalDocumentSourceSftpCredentialReferenceBinding,
    event_type: str,
):
    if event_type == "requested":
        return (
            binding.requested_by_id,
            binding.requested_at,
            binding.request_reason,
            "pending_second_approval",
            binding.request_hash,
        )
    if event_type == "approved":
        return (
            binding.approved_by_id,
            binding.approved_at,
            binding.approval_reason,
            "active",
            binding.approval_hash,
        )
    if event_type in {"rejected", "disabled"}:
        return (
            binding.terminal_by_id,
            binding.terminal_at,
            binding.terminal_reason,
            binding.status,
            binding.terminal_hash,
        )
    raise ExternalDocumentSourceConflictError(
        "SFTP credential reference receipt event is invalid"
    )


def _ensure_integrity(
    db: Session,
    binding: ExternalDocumentSourceSftpCredentialReferenceBinding,
) -> None:
    profile = _profile_for_binding(db, binding)
    expected_locator = _locator_hash(
        authentication_kind=binding.authentication_kind,
        backend=binding.reference_backend,
        namespace=binding.reference_namespace,
        name=binding.reference_name,
        version=binding.reference_version,
    )
    if binding.locator_hash != expected_locator:
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference locator integrity failed"
        )
    expected_scope = _scope_hash(
        organization_id=binding.organization_id,
        profile=profile,
        authentication_kind=binding.authentication_kind,
        locator_hash=binding.locator_hash,
        request_key=binding.request_key,
    )
    if (
        binding.scope_hash != expected_scope
        or binding.request_hash != _request_hash(binding)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference request integrity failed"
        )
    if not binding.credential_reference_stored or any(
        bool(getattr(binding, field)) for field in _SAFETY_FIELDS
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference safety boundary drifted"
        )
    if (
        binding.approval_hash is not None
        and binding.approval_hash != _approval_hash(binding)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference approval integrity failed"
        )
    if (
        binding.status in {"active", "disabled"}
        and binding.requested_by_id == binding.approved_by_id
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference four-eyes boundary drifted"
        )
    if binding.terminal_hash is not None and binding.terminal_hash != _terminal_hash(
        binding
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference terminal integrity failed"
        )

    rows = _receipts(db, binding)
    expected_events = _expected_events(binding)
    if len(rows) != len(expected_events) or [
        row.event_type for row in rows
    ] != expected_events:
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference receipt lifecycle is incomplete"
        )

    prior: str | None = None
    for sequence_number, receipt in enumerate(rows, start=1):
        if (
            receipt.sequence_number != sequence_number
            or receipt.prior_receipt_hash != prior
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP credential reference receipt chain linkage failed"
            )
        if (
            receipt.scope_hash != binding.scope_hash
            or not receipt.credential_reference_stored
            or any(bool(getattr(receipt, field)) for field in _SAFETY_FIELDS)
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP credential reference receipt safety/scope drifted"
            )
        (
            expected_actor,
            expected_time,
            expected_reason,
            expected_status,
            expected_decision,
        ) = _expected_receipt_facts(binding, receipt.event_type)
        if (
            expected_actor is None
            or expected_time is None
            or expected_reason is None
            or expected_decision is None
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP credential reference receipt facts are incomplete"
            )
        if (
            receipt.actor_id != expected_actor
            or _aware(receipt.occurred_at) != _aware(expected_time)
            or receipt.reason != expected_reason
            or receipt.status_after != expected_status
            or receipt.decision_hash != expected_decision
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP credential reference receipt integrity failed"
            )
        prior = receipt.receipt_hash


def _append_receipt(
    db: Session,
    *,
    binding: ExternalDocumentSourceSftpCredentialReferenceBinding,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    reason: str,
    decision_hash: str,
) -> None:
    rows = _receipts(db, binding)
    receipt = ExternalDocumentSourceSftpCredentialReferenceReceipt(
        organization_id=binding.organization_id,
        binding_id=binding.id,
        sequence_number=len(rows) + 1,
        event_type=event_type,
        status_after=binding.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=reason,
        scope_hash=binding.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=rows[-1].receipt_hash if rows else None,
        credential_reference_stored=True,
        **{field: False for field in _SAFETY_FIELDS},
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def request_external_document_source_sftp_credential_reference(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    authentication_kind: str,
    reference_backend: str,
    reference_namespace: str,
    reference_name: str,
    reference_version: str | None,
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
    auth_kind = _normalize_authentication_kind(authentication_kind)
    backend = _normalize_backend(reference_backend)
    namespace = _normalize_locator_component(
        reference_namespace,
        field="reference_namespace",
        maximum=128,
    )
    name = _normalize_locator_component(
        reference_name,
        field="reference_name",
        maximum=128,
    )
    version = (
        _normalize_locator_component(
            reference_version,
            field="reference_version",
            maximum=64,
            version=True,
        )
        if reference_version is not None
        else None
    )
    locator_hash = _locator_hash(
        authentication_kind=auth_kind,
        backend=backend,
        namespace=namespace,
        name=name,
        version=version,
    )

    profile = get_external_document_source_profile(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
    )
    _require_active_sftp_profile(profile)
    scope_hash = _scope_hash(
        organization_id=organization_id,
        profile=profile,
        authentication_kind=auth_kind,
        locator_hash=locator_hash,
        request_key=normalized_key,
    )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpCredentialReferenceBinding).where(
            ExternalDocumentSourceSftpCredentialReferenceBinding.profile_id == profile_id
        )
    )
    if existing is not None:
        if existing.organization_id != organization_id:
            raise ExternalDocumentSourceNotFoundError(
                "SFTP source profile not found"
            )
        _ensure_integrity(db, existing)
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
            or existing.authentication_kind != auth_kind
            or existing.reference_backend != backend
            or existing.reference_namespace != namespace
            or existing.reference_name != name
            or existing.reference_version != version
            or existing.locator_hash != locator_hash
            or existing.scope_hash != scope_hash
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP source profile already has a different credential reference binding"
            )
        return existing, "unchanged"

    current = _aware(now or _utc_now())
    binding = ExternalDocumentSourceSftpCredentialReferenceBinding(
        organization_id=organization_id,
        profile_id=profile.id,
        provider_kind="sftp",
        profile_hash=profile.profile_hash,
        authentication_kind=auth_kind,
        reference_backend=backend,
        reference_namespace=namespace,
        reference_name=name,
        reference_version=version,
        locator_hash=locator_hash,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="",
        status="pending_second_approval",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current,
        credential_reference_stored=True,
        **{field: False for field in _SAFETY_FIELDS},
    )
    db.add(binding)
    db.flush()
    binding.request_hash = _request_hash(binding)
    _append_receipt(
        db,
        binding=binding,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=current,
        reason=normalized_reason,
        decision_hash=binding.request_hash,
    )
    db.flush()
    _ensure_integrity(db, binding)
    return binding, "requested"


def approve_external_document_source_sftp_credential_reference(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
    approved_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    reason = _normalize_text(
        decision_reason,
        field="reason",
        minimum=8,
        maximum=2000,
    )
    binding = _get_binding(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    _ensure_integrity(db, binding)
    profile = _profile_for_binding(db, binding)
    _require_active_sftp_profile(profile)
    if binding.status == "active":
        if (
            binding.approved_by_id == approved_by_id
            and binding.approval_reason == reason
        ):
            return binding, "unchanged"
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference binding is already approved"
        )
    if binding.status != "pending_second_approval":
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference binding is not pending approval"
        )
    if binding.requested_by_id == approved_by_id:
        raise ExternalDocumentSourceConflictError(
            "Independent second approval is required"
        )

    current = _aware(now or _utc_now())
    binding.status = "active"
    binding.approved_by_id = approved_by_id
    binding.approved_at = current
    binding.approval_reason = reason
    binding.approval_hash = _approval_hash(binding)
    _append_receipt(
        db,
        binding=binding,
        event_type="approved",
        actor_id=approved_by_id,
        occurred_at=current,
        reason=reason,
        decision_hash=binding.approval_hash,
    )
    db.flush()
    _ensure_integrity(db, binding)
    return binding, "approved"


def reject_external_document_source_sftp_credential_reference(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
    rejected_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    reason = _normalize_text(
        decision_reason,
        field="reason",
        minimum=8,
        maximum=2000,
    )
    binding = _get_binding(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    _ensure_integrity(db, binding)
    if binding.status == "rejected":
        if (
            binding.terminal_by_id == rejected_by_id
            and binding.terminal_reason == reason
        ):
            return binding, "unchanged"
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference binding is already rejected"
        )
    if binding.status != "pending_second_approval":
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference binding is not pending rejection"
        )

    current = _aware(now or _utc_now())
    binding.status = "rejected"
    binding.terminal_by_id = rejected_by_id
    binding.terminal_at = current
    binding.terminal_reason = reason
    binding.terminal_hash = _terminal_hash(binding)
    _append_receipt(
        db,
        binding=binding,
        event_type="rejected",
        actor_id=rejected_by_id,
        occurred_at=current,
        reason=reason,
        decision_hash=binding.terminal_hash,
    )
    db.flush()
    _ensure_integrity(db, binding)
    return binding, "rejected"


def disable_external_document_source_sftp_credential_reference(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
    disabled_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    reason = _normalize_text(
        decision_reason,
        field="reason",
        minimum=8,
        maximum=2000,
    )
    binding = _get_binding(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    _ensure_integrity(db, binding)
    if binding.status == "disabled":
        if (
            binding.terminal_by_id == disabled_by_id
            and binding.terminal_reason == reason
        ):
            return binding, "unchanged"
        raise ExternalDocumentSourceConflictError(
            "SFTP credential reference binding is already disabled"
        )
    if binding.status != "active":
        raise ExternalDocumentSourceConflictError(
            "Only an active SFTP credential reference binding may be disabled"
        )

    current = _aware(now or _utc_now())
    binding.status = "disabled"
    binding.terminal_by_id = disabled_by_id
    binding.terminal_at = current
    binding.terminal_reason = reason
    binding.terminal_hash = _terminal_hash(binding)
    _append_receipt(
        db,
        binding=binding,
        event_type="disabled",
        actor_id=disabled_by_id,
        occurred_at=current,
        reason=reason,
        decision_hash=binding.terminal_hash,
    )
    db.flush()
    _ensure_integrity(db, binding)
    return binding, "disabled"


def get_external_document_source_sftp_credential_reference(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
) -> ExternalDocumentSourceSftpCredentialReferenceBinding:
    binding = _get_binding(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    _ensure_integrity(db, binding)
    if binding.status in {"pending_second_approval", "active"}:
        _require_active_sftp_profile(_profile_for_binding(db, binding))
    return binding


def list_external_document_source_sftp_credential_reference_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    binding_id: UUID,
) -> list[ExternalDocumentSourceSftpCredentialReferenceReceipt]:
    binding = get_external_document_source_sftp_credential_reference(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        binding_id=binding_id,
    )
    return _receipts(db, binding)

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.models import Claim
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt,
)
from app.modules.external_document_sources.sftp_generation3_change_detection_models import (
    ExternalDocumentSourceSftpGeneration3ChangeDetection,
)
from app.modules.external_document_sources.sftp_generation3_change_detection_service import (
    get_external_document_source_sftp_generation3_change_detection,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_service import (
    _ensure_integrity as _ensure_generation3_checkpoint_integrity,
)
from app.modules.external_document_sources.sftp_generation3_restaging_models import (
    ExternalDocumentSourceSftpGeneration3Restaging,
)
from app.modules.external_document_sources.sftp_generation3_restaging_service import (
    _ensure_integrity as _ensure_generation3_restaging_integrity,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _aware(value).isoformat()


def _canonical_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
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


def _safety() -> dict[str, bool]:
    return {
        "upstream_generation3_checkpoint_completed": True,
        "upstream_generation3_observation_completed": True,
        "latest_generation3_observation_confirmed": True,
        "remote_version_current_at_authorization": True,
        "human_authorization_recorded": True,
        "credential_stored": False,
        "session_stored": False,
        "provider_network_performed": False,
        "ssh_transport_performed": False,
        "authentication_performed": False,
        "sftp_session_opened": False,
        "remote_content_transiently_observed": False,
        "remote_list_performed": False,
        "remote_stat_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_reconciliation_performed": False,
        "durable_content_staged": False,
        "checkpoint_created": False,
        "checkpoint_advanced": False,
        "document_created": False,
        "evidence_admitted": False,
        "content_parsed": False,
        "content_extracted": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
        "background_sync_started": False,
    }


def _active_claim(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> Claim:
    claim = db.scalar(
        select(Claim).where(
            Claim.id == claim_id,
            Claim.organization_id == organization_id,
            Claim.deleted_at.is_(None),
        )
    )
    if claim is None:
        raise ExternalDocumentSourceNotFoundError("Claim not found")
    return claim


def _load_generation3_lineage(
    db: Session,
    observation: ExternalDocumentSourceSftpGeneration3ChangeDetection,
    *,
    lock_checkpoint: bool,
):
    checkpoint_stmt = select(
        ExternalDocumentSourceSftpGeneration3CheckpointAdvancement
    ).where(
        ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.id
        == observation.generation3_checkpoint_advancement_id,
        ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.organization_id
        == observation.organization_id,
        ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.profile_id
        == observation.profile_id,
    )
    if lock_checkpoint:
        checkpoint_stmt = checkpoint_stmt.with_for_update()
    checkpoint = db.scalar(checkpoint_stmt)
    if checkpoint is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 checkpoint authorization lineage is missing"
        )
    _ensure_generation3_checkpoint_integrity(db, checkpoint)

    candidate = db.scalar(
        select(ExternalDocumentSourceSftpGeneration3Restaging).where(
            ExternalDocumentSourceSftpGeneration3Restaging.id
            == checkpoint.generation3_restaging_id,
            ExternalDocumentSourceSftpGeneration3Restaging.organization_id
            == observation.organization_id,
            ExternalDocumentSourceSftpGeneration3Restaging.profile_id
            == observation.profile_id,
        )
    )
    if candidate is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 restaging authorization lineage is missing"
        )
    _ensure_generation3_restaging_integrity(
        db,
        candidate,
        verify_storage=False,
    )

    if (
        observation.generation3_restaging_id != candidate.id
        or observation.provider_kind != "sftp"
        or checkpoint.provider_kind != "sftp"
        or candidate.provider_kind != "sftp"
        or observation.profile_hash != checkpoint.profile_hash
        or observation.profile_hash != candidate.profile_hash
        or observation.successor_checkpoint_state_hash
        != checkpoint.successor_checkpoint_state_hash
        or observation.successor_checkpoint_completion_hash
        != checkpoint.completion_hash
        or observation.candidate_content_proof_hash != candidate.content_proof_hash
        or observation.candidate_completion_hash != candidate.completion_hash
        or observation.baseline_projection_hash != candidate.observed_projection_hash
        or observation.baseline_byte_size != checkpoint.content_byte_count
        or checkpoint.content_sha256 != candidate.content_sha256
        or checkpoint.content_byte_count != candidate.content_byte_count
        or checkpoint.storage_object_key_hash != candidate.storage_object_key_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission authorization upstream lineage drifted"
        )
    return checkpoint, candidate


def _latest_completed_observation(
    db: Session,
    *,
    observation: ExternalDocumentSourceSftpGeneration3ChangeDetection,
) -> ExternalDocumentSourceSftpGeneration3ChangeDetection | None:
    return db.scalar(
        select(ExternalDocumentSourceSftpGeneration3ChangeDetection)
        .where(
            ExternalDocumentSourceSftpGeneration3ChangeDetection.organization_id
            == observation.organization_id,
            ExternalDocumentSourceSftpGeneration3ChangeDetection.profile_id
            == observation.profile_id,
            ExternalDocumentSourceSftpGeneration3ChangeDetection.generation3_checkpoint_advancement_id
            == observation.generation3_checkpoint_advancement_id,
        )
        .order_by(
            ExternalDocumentSourceSftpGeneration3ChangeDetection.completed_at.desc(),
            ExternalDocumentSourceSftpGeneration3ChangeDetection.created_at.desc(),
            ExternalDocumentSourceSftpGeneration3ChangeDetection.id.desc(),
        )
        .limit(1)
    )


def _eligible_observation(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
    require_latest: bool,
    lock_checkpoint: bool,
):
    observation = get_external_document_source_sftp_generation3_change_detection(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    checkpoint, candidate = _load_generation3_lineage(
        db,
        observation,
        lock_checkpoint=lock_checkpoint,
    )
    if lock_checkpoint:
        observation = get_external_document_source_sftp_generation3_change_detection(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            execution_id=execution_id,
        )
        if observation.generation3_checkpoint_advancement_id != checkpoint.id:
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 observation checkpoint lineage changed during authorization"
            )

    if (
        observation.result_status != "unchanged"
        or observation.observed_projection_hash is None
        or observation.observed_projection_hash != observation.baseline_projection_hash
        or observation.observed_entry_kind != "file"
        or observation.observed_byte_size is None
        or observation.changed_dimensions is not None
        or observation.completion_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-R observation is not an unchanged complete file observation eligible for authorization"
        )

    if require_latest:
        latest = _latest_completed_observation(db, observation=observation)
        if latest is None or latest.id != observation.id:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-R observation is stale because a newer completed generation-3 observation exists"
            )
    return observation, checkpoint, candidate


def _scope_hash(
    *,
    organization_id: UUID,
    claim_id: UUID,
    profile_id: UUID,
    observation: ExternalDocumentSourceSftpGeneration3ChangeDetection,
    checkpoint: ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
    candidate: ExternalDocumentSourceSftpGeneration3Restaging,
    request_key: str,
) -> str:
    return _canonical_hash({
        "organization_id": str(organization_id),
        "claim_id": str(claim_id),
        "profile_id": str(profile_id),
        "generation3_change_detection_id": str(observation.id),
        "generation3_checkpoint_advancement_id": str(checkpoint.id),
        "generation3_restaging_id": str(candidate.id),
        "provider_kind": observation.provider_kind,
        "profile_hash": observation.profile_hash,
        "authorized_projection_hash": observation.observed_projection_hash,
        "authorized_entry_hash": observation.baseline_entry_hash,
        "authorized_relative_path_hash": observation.baseline_relative_path_hash,
        "authorized_byte_size": observation.observed_byte_size,
        "authorized_modified_at": _iso(observation.observed_modified_at),
        "authorized_metadata_id_hash": observation.observed_metadata_id_hash,
        "authorized_content_sha256": checkpoint.content_sha256,
        "authorized_storage_object_key_hash": checkpoint.storage_object_key_hash,
        "storage_backend_kind": checkpoint.storage_backend_kind,
        "storage_purpose": checkpoint.storage_purpose,
        "checkpoint_state_hash": checkpoint.successor_checkpoint_state_hash,
        "checkpoint_completion_hash": checkpoint.completion_hash,
        "candidate_content_proof_hash": candidate.content_proof_hash,
        "candidate_completion_hash": candidate.completion_hash,
        "observation_completion_hash": observation.completion_hash,
        "request_key": request_key,
        "provider_io_authorized": False,
        "storage_io_authorized": False,
        "document_creation_authorized": False,
        "processing_authorized": False,
    })


def _request_hash(
    authorization: ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
) -> str:
    return _canonical_hash({
        "authorization_id": str(authorization.id),
        "scope_hash": authorization.scope_hash,
        "authorized_by_id": str(authorization.authorized_by_id),
        "authorization_reason": authorization.authorization_reason,
        "authorized_at": _iso(authorization.authorized_at),
        **_safety(),
    })


def _authorization_hash(
    authorization: ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
) -> str:
    return _canonical_hash({
        "authorization_id": str(authorization.id),
        "scope_hash": authorization.scope_hash,
        "request_hash": authorization.request_hash,
        "status": authorization.status,
        "claim_id": str(authorization.claim_id),
        "generation3_change_detection_id": str(
            authorization.generation3_change_detection_id
        ),
        "generation3_checkpoint_advancement_id": str(
            authorization.generation3_checkpoint_advancement_id
        ),
        "generation3_restaging_id": str(authorization.generation3_restaging_id),
        "authorized_projection_hash": authorization.authorized_projection_hash,
        "authorized_entry_hash": authorization.authorized_entry_hash,
        "authorized_relative_path_hash": authorization.authorized_relative_path_hash,
        "authorized_byte_size": authorization.authorized_byte_size,
        "authorized_modified_at": _iso(authorization.authorized_modified_at),
        "authorized_metadata_id_hash": authorization.authorized_metadata_id_hash,
        "authorized_content_sha256": authorization.authorized_content_sha256,
        "authorized_storage_object_key_hash": authorization.authorized_storage_object_key_hash,
        "checkpoint_state_hash": authorization.checkpoint_state_hash,
        "checkpoint_completion_hash": authorization.checkpoint_completion_hash,
        "candidate_content_proof_hash": authorization.candidate_content_proof_hash,
        "candidate_completion_hash": authorization.candidate_completion_hash,
        "observation_completion_hash": authorization.observation_completion_hash,
        **_safety(),
    })


def _receipt_hash(
    receipt: ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt,
) -> str:
    return _canonical_hash({
        "receipt_id": str(receipt.id),
        "organization_id": str(receipt.organization_id),
        "authorization_id": str(receipt.authorization_id),
        "sequence_number": receipt.sequence_number,
        "event_type": receipt.event_type,
        "status_after": receipt.status_after,
        "actor_id": str(receipt.actor_id),
        "occurred_at": _iso(receipt.occurred_at),
        "reason": receipt.reason,
        "scope_hash": receipt.scope_hash,
        "decision_hash": receipt.decision_hash,
        "prior_receipt_hash": receipt.prior_receipt_hash,
        **_safety(),
    })


def _receipts(
    db: Session,
    authorization: ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
):
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt)
            .where(
                ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt.organization_id
                == authorization.organization_id,
                ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt.authorization_id
                == authorization.id,
            )
            .order_by(
                ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt.sequence_number.asc()
            )
        ).all()
    )


def _ensure_integrity(
    db: Session,
    authorization: ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
) -> None:
    claim = db.scalar(
        select(Claim).where(
            Claim.id == authorization.claim_id,
            Claim.organization_id == authorization.organization_id,
        )
    )
    if claim is None:
        raise ExternalDocumentSourceConflictError(
            "Authorized Claim lineage is missing"
        )

    observation, checkpoint, candidate = _eligible_observation(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        execution_id=authorization.generation3_change_detection_id,
        require_latest=False,
        lock_checkpoint=False,
    )
    expected = {
        "generation3_checkpoint_advancement_id": checkpoint.id,
        "generation3_restaging_id": candidate.id,
        "provider_kind": observation.provider_kind,
        "profile_hash": observation.profile_hash,
        "authorized_projection_hash": observation.observed_projection_hash,
        "authorized_entry_hash": observation.baseline_entry_hash,
        "authorized_relative_path_hash": observation.baseline_relative_path_hash,
        "authorized_byte_size": observation.observed_byte_size,
        "authorized_modified_at": observation.observed_modified_at,
        "authorized_metadata_id_hash": observation.observed_metadata_id_hash,
        "authorized_content_sha256": checkpoint.content_sha256,
        "authorized_storage_object_key_hash": checkpoint.storage_object_key_hash,
        "storage_backend_kind": checkpoint.storage_backend_kind,
        "storage_purpose": checkpoint.storage_purpose,
        "checkpoint_state_hash": checkpoint.successor_checkpoint_state_hash,
        "checkpoint_completion_hash": checkpoint.completion_hash,
        "candidate_content_proof_hash": candidate.content_proof_hash,
        "candidate_completion_hash": candidate.completion_hash,
        "observation_completion_hash": observation.completion_hash,
    }
    for field, expected_value in expected.items():
        actual = getattr(authorization, field)
        if isinstance(expected_value, datetime) and isinstance(actual, datetime):
            if _aware(actual) != _aware(expected_value):
                raise ExternalDocumentSourceConflictError(
                    f"SFTP Evidence admission authorization integrity drifted at {field}"
                )
        elif actual != expected_value:
            raise ExternalDocumentSourceConflictError(
                f"SFTP Evidence admission authorization integrity drifted at {field}"
            )

    if authorization.status != "authorized":
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission authorization lifecycle drifted"
        )
    expected_scope = _scope_hash(
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        profile_id=authorization.profile_id,
        observation=observation,
        checkpoint=checkpoint,
        candidate=candidate,
        request_key=authorization.request_key,
    )
    if authorization.scope_hash != expected_scope:
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission authorization scope hash drifted"
        )
    if authorization.request_hash != _request_hash(authorization):
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission authorization request hash drifted"
        )
    if authorization.authorization_hash != _authorization_hash(authorization):
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission authorization decision hash drifted"
        )
    for field, expected_value in _safety().items():
        if bool(getattr(authorization, field)) != expected_value:
            raise ExternalDocumentSourceConflictError(
                "SFTP Evidence admission authorization safety boundary drifted"
            )

    rows = _receipts(db, authorization)
    if len(rows) != 1:
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission authorization receipt lifecycle drifted"
        )
    receipt = rows[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != "authorized"
        or receipt.status_after != "authorized"
        or receipt.actor_id != authorization.authorized_by_id
        or _aware(receipt.occurred_at) != _aware(authorization.authorized_at)
        or receipt.reason != authorization.authorization_reason
        or receipt.scope_hash != authorization.scope_hash
        or receipt.decision_hash != authorization.authorization_hash
        or receipt.prior_receipt_hash is not None
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP Evidence admission authorization receipt integrity drifted"
        )
    for field, expected_value in _safety().items():
        if bool(getattr(receipt, field)) != expected_value:
            raise ExternalDocumentSourceConflictError(
                "SFTP Evidence admission authorization receipt safety boundary drifted"
            )


def authorize_external_document_source_sftp_evidence_admission(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    generation3_change_detection_id: UUID,
    claim_id: UUID,
    authorized_by_id: UUID,
    request_key: str,
    authorization_reason: str,
):
    request_key = _normalize_text(
        request_key,
        field="request_key",
        minimum=1,
        maximum=128,
    )
    authorization_reason = _normalize_text(
        authorization_reason,
        field="reason",
        minimum=8,
        maximum=2000,
    )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionAuthorization).where(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.profile_id
            == profile_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.request_key
            == request_key,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.claim_id != claim_id
            or existing.generation3_change_detection_id
            != generation3_change_detection_id
            or existing.authorized_by_id != authorized_by_id
            or existing.authorization_reason != authorization_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "request_key is already bound to a different SFTP Evidence admission authorization"
            )
        return existing, "replayed"

    _active_claim(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
    )

    initial = get_external_document_source_sftp_generation3_change_detection(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=generation3_change_detection_id,
    )
    observation, checkpoint, candidate = _eligible_observation(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=initial.id,
        require_latest=True,
        lock_checkpoint=True,
    )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionAuthorization).where(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.profile_id
            == profile_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.request_key
            == request_key,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.claim_id != claim_id
            or existing.generation3_change_detection_id != observation.id
            or existing.authorized_by_id != authorized_by_id
            or existing.authorization_reason != authorization_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "request_key is already bound to a different SFTP Evidence admission authorization"
            )
        return existing, "replayed"

    authorized_at = _utc_now()
    authorization = ExternalDocumentSourceSftpEvidenceAdmissionAuthorization(
        id=uuid4(),
        organization_id=organization_id,
        claim_id=claim_id,
        profile_id=profile_id,
        generation3_change_detection_id=observation.id,
        generation3_checkpoint_advancement_id=checkpoint.id,
        generation3_restaging_id=candidate.id,
        provider_kind="sftp",
        profile_hash=observation.profile_hash,
        authorized_projection_hash=observation.observed_projection_hash,
        authorized_entry_hash=observation.baseline_entry_hash,
        authorized_relative_path_hash=observation.baseline_relative_path_hash,
        authorized_byte_size=observation.observed_byte_size,
        authorized_modified_at=observation.observed_modified_at,
        authorized_metadata_id_hash=observation.observed_metadata_id_hash,
        authorized_content_sha256=checkpoint.content_sha256,
        authorized_storage_object_key_hash=checkpoint.storage_object_key_hash,
        storage_backend_kind=checkpoint.storage_backend_kind,
        storage_purpose=checkpoint.storage_purpose,
        checkpoint_state_hash=checkpoint.successor_checkpoint_state_hash,
        checkpoint_completion_hash=checkpoint.completion_hash,
        candidate_content_proof_hash=candidate.content_proof_hash,
        candidate_completion_hash=candidate.completion_hash,
        observation_completion_hash=observation.completion_hash,
        request_key=request_key,
        scope_hash="",
        request_hash="",
        status="authorized",
        authorized_by_id=authorized_by_id,
        authorization_reason=authorization_reason,
        authorized_at=authorized_at,
        authorization_hash="",
        **_safety(),
    )
    authorization.scope_hash = _scope_hash(
        organization_id=organization_id,
        claim_id=claim_id,
        profile_id=profile_id,
        observation=observation,
        checkpoint=checkpoint,
        candidate=candidate,
        request_key=request_key,
    )
    authorization.request_hash = _request_hash(authorization)
    authorization.authorization_hash = _authorization_hash(authorization)
    db.add(authorization)
    db.flush()

    receipt = ExternalDocumentSourceSftpEvidenceAdmissionAuthorizationReceipt(
        id=uuid4(),
        organization_id=organization_id,
        authorization_id=authorization.id,
        sequence_number=1,
        event_type="authorized",
        status_after="authorized",
        actor_id=authorized_by_id,
        occurred_at=authorized_at,
        reason=authorization_reason,
        scope_hash=authorization.scope_hash,
        decision_hash=authorization.authorization_hash,
        prior_receipt_hash=None,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    _ensure_integrity(db, authorization)
    return authorization, "authorized"


def get_external_document_source_sftp_evidence_admission_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
):
    authorization = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionAuthorization).where(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.id
            == authorization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.organization_id
            == organization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.profile_id
            == profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP Evidence admission authorization not found"
        )
    _ensure_integrity(db, authorization)
    return authorization


def list_external_document_source_sftp_evidence_admission_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
):
    authorization = (
        get_external_document_source_sftp_evidence_admission_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
        )
    )
    return _receipts(db, authorization)

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.retention_disposal_dry_run_service import _as_utc
from app.modules.claims.retention_disposal_manifest_service import (
    revalidate_disposal_execution_manifest,
)
from app.modules.claims.retention_disposal_release_models import DisposalReleaseReview
from app.modules.claims.retention_disposal_release_service import (
    _approval_hash as _release_approval_hash,
    _live_snapshot_matches,
    _revalidate_live_stage,
    _stored_review_integrity_ok,
)
from app.modules.claims.retention_physical_disposal_authorization_models import (
    PhysicalDisposalAdmissionAuthorization,
)
from app.modules.claims.retention_service import RetentionNotFoundError, get_claim_for_retention
from app.modules.documents.recovery_durable_authoritative_storage_health_models import (
    EvidenceRecoveryDurableAuthoritativeStorageHealthQualification,
)
from app.modules.documents.recovery_durable_authoritative_storage_health_service import (
    RecoveryDurableAuthoritativeStorageHealthError,
    _durable_an_snapshot,
    _matches_snapshot,
    _qualification_hash,
)

PHYSICAL_DISPOSAL_ADMISSION_WINDOW = timedelta(minutes=5)


class PhysicalDisposalAdmissionError(ValueError):
    def __init__(self, *blocking_reasons: str):
        self.blocking_reasons = [reason for reason in blocking_reasons if reason]
        super().__init__(
            "Physical disposal admission failed: " + ", ".join(self.blocking_reasons)
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _as_utc(value).isoformat()


def _canonical_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_reason(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < 5:
        raise ValueError("Physical disposal authorization reason must contain at least 5 characters")
    if len(normalized) > 2000:
        raise ValueError("Physical disposal authorization reason must not exceed 2000 characters")
    return normalized


def _stored_ao_integrity_ok(
    qualification: EvidenceRecoveryDurableAuthoritativeStorageHealthQualification,
) -> bool:
    expected = _qualification_hash(
        request_snapshot_hash=qualification.request_snapshot_hash,
        requested_by_id=qualification.requested_by_id,
        requested_at=_as_utc(qualification.requested_at),
        review_expires_at=_as_utc(qualification.review_expires_at),
        reason=qualification.request_reason,
    )
    return expected == qualification.health_qualification_hash


def _document_binding(
    row: dict,
    qualification: EvidenceRecoveryDurableAuthoritativeStorageHealthQualification,
) -> dict:
    binding = {
        "document_id": str(qualification.document_id),
        "ao_health_qualification_id": str(qualification.id),
        "ao_health_qualification_hash": qualification.health_qualification_hash,
        "ratification_id": str(qualification.ratification_id),
        "ratification_hash": qualification.ratification_hash,
        "integrity_proof_hash": qualification.integrity_proof_hash,
        "file_hash": row["file_hash"],
        "file_size_bytes": int(row["file_size_bytes"]),
        "storage_key_fingerprint": row["storage_key_fingerprint"],
        "row_fingerprint": row["row_fingerprint"],
    }
    binding["binding_hash"] = _canonical_hash(binding)
    return binding


def _authorization_hash(
    *,
    release_review_id: UUID,
    release_review_hash: str,
    release_approval_hash: str,
    manifest_hash: str,
    inventory_hash: str,
    document_bindings_hash: str,
    requested_by_id: UUID,
    request_reason: str,
    requested_at: datetime,
    authorization_expires_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "release_review_id": str(release_review_id),
            "release_review_hash": release_review_hash,
            "release_approval_hash": release_approval_hash,
            "manifest_hash": manifest_hash,
            "inventory_hash": inventory_hash,
            "document_bindings_hash": document_bindings_hash,
            "requested_by_id": str(requested_by_id),
            "request_reason": request_reason,
            "requested_at": _iso(requested_at),
            "authorization_expires_at": _iso(authorization_expires_at),
            "max_execution_count": 1,
            "execution_count": 0,
            "destructive_action_performed": False,
            "storage_write_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )


def _approval_hash(
    authorization: PhysicalDisposalAdmissionAuthorization,
    *,
    approved_by_id: UUID,
    approved_at: datetime,
    approval_reason: str,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "document_bindings_hash": authorization.document_bindings_hash,
            "approved_by_id": str(approved_by_id),
            "approved_at": _iso(approved_at),
            "approval_reason": approval_reason,
            "physical_disposal_authorized": True,
            "max_execution_count": 1,
            "execution_count": 0,
            "destructive_action_performed": False,
            "storage_write_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )


def _get_release_review(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    review_id: UUID,
) -> DisposalReleaseReview:
    review = db.scalar(
        select(DisposalReleaseReview).where(
            DisposalReleaseReview.id == review_id,
            DisposalReleaseReview.organization_id == organization_id,
            DisposalReleaseReview.claim_id == claim_id,
        )
    )
    if review is None:
        raise RetentionNotFoundError("Disposal release review not found")
    return review


def _verify_release_review_and_manifest(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    review_id: UUID,
    actor_id: UUID,
    now: datetime,
):
    review = _get_release_review(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        review_id=review_id,
    )
    if review.status != "approved":
        raise PhysicalDisposalAdmissionError("release_review_not_approved")
    if not _stored_review_integrity_ok(review):
        raise PhysicalDisposalAdmissionError("release_review_integrity_mismatch")
    if (
        review.approved_by_id is None
        or review.approved_at is None
        or review.approval_reason is None
        or review.approval_hash is None
    ):
        raise PhysicalDisposalAdmissionError("release_review_approval_evidence_missing")
    expected_release_approval_hash = _release_approval_hash(
        review,
        approved_by_id=review.approved_by_id,
        approved_at=_as_utc(review.approved_at),
        approval_reason=review.approval_reason,
        stage_last_revalidated_at=review.last_revalidated_at,
    )
    if expected_release_approval_hash != review.approval_hash:
        raise PhysicalDisposalAdmissionError("release_review_approval_hash_mismatch")
    if now >= _as_utc(review.quarantine_stage_expires_at):
        raise PhysicalDisposalAdmissionError("quarantine_stage_expired")

    stage = _revalidate_live_stage(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        stage_id=review.disposal_quarantine_stage_id,
        actor_id=actor_id,
        now=now,
    )
    if not _live_snapshot_matches(review, stage):
        raise PhysicalDisposalAdmissionError("release_review_live_snapshot_drift")

    manifest, outcome = revalidate_disposal_execution_manifest(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        manifest_id=review.disposal_execution_manifest_id,
        actor_id=actor_id,
        now=now,
    )
    if outcome not in {"ready", "revalidated", "unchanged"} or manifest.status != "ready":
        raise PhysicalDisposalAdmissionError(f"manifest_not_ready:{outcome}")
    if not all(
        (
            manifest.id == review.disposal_execution_manifest_id,
            manifest.manifest_hash == review.manifest_hash,
            manifest.inventory_hash == review.inventory_hash,
            manifest.document_count == review.document_count,
            manifest.total_file_size_bytes == review.total_file_size_bytes,
        )
    ):
        raise PhysicalDisposalAdmissionError("release_review_manifest_drift")
    return review, manifest, stage


def _fresh_document_bindings(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    inventory: list[dict],
    expected_document_count: int,
    now: datetime,
) -> list[dict]:
    document_rows = [row for row in inventory if row.get("object_kind") == "document"]
    if expected_document_count <= 0 or len(document_rows) != expected_document_count:
        raise PhysicalDisposalAdmissionError("manifest_document_count_mismatch")

    bindings: list[dict] = []
    for row in sorted(document_rows, key=lambda item: str(item.get("object_id", ""))):
        try:
            document_id = UUID(str(row["object_id"]))
            file_hash = str(row["file_hash"])
            file_size_bytes = int(row["file_size_bytes"])
            storage_key_fingerprint = str(row["storage_key_fingerprint"])
            row_fingerprint = str(row["row_fingerprint"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PhysicalDisposalAdmissionError("manifest_document_binding_incomplete") from exc

        candidates = list(
            db.scalars(
                select(EvidenceRecoveryDurableAuthoritativeStorageHealthQualification)
                .where(
                    EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.organization_id
                    == organization_id,
                    EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.claim_id
                    == claim_id,
                    EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.document_id
                    == document_id,
                    EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.status
                    == "qualified",
                )
                .order_by(
                    EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.qualified_at.desc(),
                    EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.id.desc(),
                )
            ).all()
        )

        matches: list[EvidenceRecoveryDurableAuthoritativeStorageHealthQualification] = []
        for qualification in candidates:
            if not _stored_ao_integrity_ok(qualification):
                continue
            try:
                snapshot = _durable_an_snapshot(
                    db,
                    organization_id=organization_id,
                    claim_id=claim_id,
                    document_id=document_id,
                    ratification_id=qualification.ratification_id,
                    now=now,
                )
            except RecoveryDurableAuthoritativeStorageHealthError:
                continue
            if not _matches_snapshot(qualification, snapshot):
                continue
            if not all(
                (
                    qualification.source_file_hash == file_hash,
                    qualification.source_file_size_bytes == file_size_bytes,
                    qualification.local_storage_key_fingerprint == storage_key_fingerprint,
                )
            ):
                continue
            matches.append(qualification)

        if len(matches) != 1:
            reason = (
                "ao_health_qualification_missing_or_stale"
                if not matches
                else "ao_health_qualification_ambiguous"
            )
            raise PhysicalDisposalAdmissionError(f"{reason}:{document_id}")

        bindings.append(
            _document_binding(
                {
                    "file_hash": file_hash,
                    "file_size_bytes": file_size_bytes,
                    "storage_key_fingerprint": storage_key_fingerprint,
                    "row_fingerprint": row_fingerprint,
                },
                matches[0],
            )
        )
    return bindings


def _verify_existing_integrity(
    authorization: PhysicalDisposalAdmissionAuthorization,
) -> None:
    if _canonical_hash(list(authorization.document_bindings or [])) != authorization.document_bindings_hash:
        raise PhysicalDisposalAdmissionError("stored_document_bindings_hash_mismatch")
    expected = _authorization_hash(
        release_review_id=authorization.disposal_release_review_id,
        release_review_hash=authorization.release_review_hash,
        release_approval_hash=authorization.release_approval_hash,
        manifest_hash=authorization.manifest_hash,
        inventory_hash=authorization.inventory_hash,
        document_bindings_hash=authorization.document_bindings_hash,
        requested_by_id=authorization.requested_by_id,
        request_reason=authorization.request_reason,
        requested_at=_as_utc(authorization.requested_at),
        authorization_expires_at=_as_utc(authorization.authorization_expires_at),
    )
    if expected != authorization.authorization_hash:
        raise PhysicalDisposalAdmissionError("stored_authorization_hash_mismatch")


def request_physical_disposal_admission(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    review_id: UUID,
    requested_by_id: UUID,
    request_reason: str,
    now: datetime | None = None,
) -> PhysicalDisposalAdmissionAuthorization:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(request_reason)
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)

    existing = db.scalar(
        select(PhysicalDisposalAdmissionAuthorization).where(
            PhysicalDisposalAdmissionAuthorization.organization_id == organization_id,
            PhysicalDisposalAdmissionAuthorization.claim_id == claim_id,
            PhysicalDisposalAdmissionAuthorization.disposal_release_review_id == review_id,
        )
    )
    if existing is not None:
        _verify_existing_integrity(existing)
        if existing.requested_by_id == requested_by_id and existing.request_reason == reason:
            return existing
        raise PhysicalDisposalAdmissionError("release_review_already_has_admission_authorization")

    review, manifest, stage = _verify_release_review_and_manifest(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        review_id=review_id,
        actor_id=requested_by_id,
        now=current_time,
    )
    bindings = _fresh_document_bindings(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        inventory=list(manifest.inventory or []),
        expected_document_count=manifest.document_count,
        now=current_time,
    )
    bindings_hash = _canonical_hash(bindings)
    authorization_expires_at = min(
        current_time + PHYSICAL_DISPOSAL_ADMISSION_WINDOW,
        _as_utc(stage.stage_expires_at),
        _as_utc(manifest.manifest_expires_at),
    )
    if authorization_expires_at <= current_time:
        raise PhysicalDisposalAdmissionError("insufficient_live_window_for_admission")

    authorization_hash = _authorization_hash(
        release_review_id=review.id,
        release_review_hash=review.review_hash,
        release_approval_hash=review.approval_hash,
        manifest_hash=manifest.manifest_hash,
        inventory_hash=manifest.inventory_hash,
        document_bindings_hash=bindings_hash,
        requested_by_id=requested_by_id,
        request_reason=reason,
        requested_at=current_time,
        authorization_expires_at=authorization_expires_at,
    )
    authorization = PhysicalDisposalAdmissionAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        disposal_release_review_id=review.id,
        disposal_quarantine_stage_id=stage.id,
        disposal_execution_manifest_id=manifest.id,
        release_review_hash=review.review_hash,
        release_approval_hash=review.approval_hash,
        manifest_hash=manifest.manifest_hash,
        inventory_hash=manifest.inventory_hash,
        document_bindings=bindings,
        document_bindings_hash=bindings_hash,
        document_count=manifest.document_count,
        total_file_size_bytes=manifest.total_file_size_bytes,
        requested_by_id=requested_by_id,
        request_reason=reason,
        requested_at=current_time,
        authorization_expires_at=authorization_expires_at,
        status="pending_second_approval",
        physical_disposal_authorized=False,
        max_execution_count=1,
        execution_count=0,
        authorization_hash=authorization_hash,
        destructive_action_performed=False,
        storage_write_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(authorization)
    db.flush()
    return authorization


def _get_admission(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
) -> PhysicalDisposalAdmissionAuthorization:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    stmt = select(PhysicalDisposalAdmissionAuthorization).where(
        PhysicalDisposalAdmissionAuthorization.id == authorization_id,
        PhysicalDisposalAdmissionAuthorization.organization_id == organization_id,
        PhysicalDisposalAdmissionAuthorization.claim_id == claim_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    authorization = db.scalar(stmt)
    if authorization is None:
        raise RetentionNotFoundError("Physical disposal admission authorization not found")
    return authorization


def list_physical_disposal_admissions(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> list[PhysicalDisposalAdmissionAuthorization]:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    return list(
        db.scalars(
            select(PhysicalDisposalAdmissionAuthorization)
            .where(
                PhysicalDisposalAdmissionAuthorization.organization_id == organization_id,
                PhysicalDisposalAdmissionAuthorization.claim_id == claim_id,
            )
            .order_by(
                PhysicalDisposalAdmissionAuthorization.created_at.desc(),
                PhysicalDisposalAdmissionAuthorization.id.desc(),
            )
        ).all()
    )


def get_physical_disposal_admission(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
) -> PhysicalDisposalAdmissionAuthorization:
    return _get_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        authorization_id=authorization_id,
    )


def approve_physical_disposal_admission(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
    approved_by_id: UUID,
    approval_reason: str,
    now: datetime | None = None,
) -> tuple[PhysicalDisposalAdmissionAuthorization, str]:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(approval_reason)
    authorization = _get_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    _verify_existing_integrity(authorization)
    if authorization.status != "pending_second_approval":
        return authorization, "unchanged"
    if authorization.requested_by_id == approved_by_id:
        raise ValueError("Physical disposal admission requester cannot approve their own authorization")
    if current_time >= _as_utc(authorization.authorization_expires_at):
        authorization.status = "expired"
        authorization.terminal_by_id = approved_by_id
        authorization.terminal_at = current_time
        authorization.terminal_reason = "Physical disposal admission validity window expired."
        return authorization, "expired"

    review, manifest, _stage = _verify_release_review_and_manifest(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        review_id=authorization.disposal_release_review_id,
        actor_id=approved_by_id,
        now=current_time,
    )
    live_bindings = _fresh_document_bindings(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        inventory=list(manifest.inventory or []),
        expected_document_count=manifest.document_count,
        now=current_time,
    )
    live_bindings_hash = _canonical_hash(live_bindings)
    if not all(
        (
            review.review_hash == authorization.release_review_hash,
            review.approval_hash == authorization.release_approval_hash,
            manifest.manifest_hash == authorization.manifest_hash,
            manifest.inventory_hash == authorization.inventory_hash,
            live_bindings_hash == authorization.document_bindings_hash,
            live_bindings == list(authorization.document_bindings or []),
        )
    ):
        authorization.status = "invalidated"
        authorization.terminal_by_id = approved_by_id
        authorization.terminal_at = current_time
        authorization.terminal_reason = "Release, manifest, or AO document binding drift detected."
        return authorization, "invalidated"

    authorization.status = "authorized"
    authorization.physical_disposal_authorized = True
    authorization.approved_by_id = approved_by_id
    authorization.approved_at = current_time
    authorization.approval_reason = reason
    authorization.approval_hash = _approval_hash(
        authorization,
        approved_by_id=approved_by_id,
        approved_at=current_time,
        approval_reason=reason,
    )
    return authorization, "authorized"


def reject_physical_disposal_admission(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
    rejected_by_id: UUID,
    rejection_reason: str,
    now: datetime | None = None,
) -> tuple[PhysicalDisposalAdmissionAuthorization, str]:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(rejection_reason)
    authorization = _get_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    _verify_existing_integrity(authorization)
    if authorization.status != "pending_second_approval":
        return authorization, "unchanged"
    if current_time >= _as_utc(authorization.authorization_expires_at):
        authorization.status = "expired"
        authorization.terminal_by_id = rejected_by_id
        authorization.terminal_at = current_time
        authorization.terminal_reason = "Physical disposal admission validity window expired."
        return authorization, "expired"
    authorization.status = "rejected"
    authorization.terminal_by_id = rejected_by_id
    authorization.terminal_at = current_time
    authorization.terminal_reason = reason
    return authorization, "rejected"

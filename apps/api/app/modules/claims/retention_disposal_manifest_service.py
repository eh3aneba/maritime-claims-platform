import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.models import Claim
from app.modules.claims.retention_disposal_manifest_models import DisposalExecutionManifest
from app.modules.claims.retention_disposal_models import DisposalAuthorization
from app.modules.claims.retention_models import TenantRetentionPolicy
from app.modules.claims.retention_service import (
    RetentionNotFoundError,
    get_claim_for_retention,
    get_current_retention_policy,
    preview_disposal_eligibility,
)
from app.modules.documents.models import Document

MANIFEST_VALIDITY_WINDOW = timedelta(hours=4)


class DisposalManifestPreflightError(ValueError):
    def __init__(self, *, outcome: str, blocking_reasons: list[str]):
        self.outcome = outcome
        self.blocking_reasons = list(blocking_reasons)
        super().__init__(
            "Disposal execution manifest preflight failed: "
            + ", ".join(self.blocking_reasons)
        )


@dataclass(frozen=True)
class _Preflight:
    authorization: DisposalAuthorization
    claim: Claim
    policy: TenantRetentionPolicy
    authorization_lineage_hash: str
    inventory: list[dict]
    inventory_hash: str
    document_count: int
    total_file_size_bytes: int
    active_hold_ids: list[str]
    pending_proposal_ids: list[str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _as_utc(value).isoformat()


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _authorization_lineage_hash(authorization: DisposalAuthorization) -> str:
    return _canonical_hash(
        {
            "id": str(authorization.id),
            "organization_id": str(authorization.organization_id),
            "claim_id": str(authorization.claim_id),
            "status": authorization.status,
            "retention_policy_id": str(authorization.retention_policy_id),
            "retention_policy_number": authorization.retention_policy_number,
            "retention_policy_hash": authorization.retention_policy_hash,
            "eligibility_snapshot_hash": authorization.eligibility_snapshot_hash,
            "state_fingerprint": authorization.state_fingerprint,
            "requested_by_id": str(authorization.requested_by_id),
            "approved_by_id": (
                None
                if authorization.approved_by_id is None
                else str(authorization.approved_by_id)
            ),
            "approved_at": _iso(authorization.approved_at),
            "authorization_expires_at": _iso(authorization.authorization_expires_at),
        }
    )


def _document_state_and_inventory(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> tuple[list[dict], list[dict], datetime | None, int]:
    documents = list(
        db.scalars(
            select(Document)
            .where(
                Document.organization_id == organization_id,
                Document.claim_id == claim_id,
            )
            .order_by(Document.id.asc())
        ).all()
    )
    authorization_state: list[dict] = []
    inventory: list[dict] = []
    newest: datetime | None = None
    total_bytes = 0

    for document in documents:
        updated_at = _as_utc(document.updated_at)
        if newest is None or updated_at > newest:
            newest = updated_at
        total_bytes += int(document.file_size_bytes)

        authorization_state.append(
            {
                "id": str(document.id),
                "file_hash": document.file_hash,
                "version_number": document.version_number,
                "is_current": document.is_current,
                "processing_status": _enum_value(document.processing_status),
                "malware_scan_status": _enum_value(document.malware_scan_status),
                "updated_at": _iso(document.updated_at),
                "deleted_at": _iso(document.deleted_at),
            }
        )

        row = {
            "object_kind": "document",
            "object_id": str(document.id),
            "document_family_id": str(document.document_family_id),
            "file_hash": document.file_hash,
            "storage_key_fingerprint": _sha256_text(document.storage_key),
            "file_size_bytes": int(document.file_size_bytes),
            "mime_type": document.mime_type,
            "version_number": document.version_number,
            "is_current": document.is_current,
            "processing_status": _enum_value(document.processing_status),
            "malware_scan_status": _enum_value(document.malware_scan_status),
            "updated_at": _iso(document.updated_at),
            "deleted_at": _iso(document.deleted_at),
        }
        row["row_fingerprint"] = _canonical_hash(row)
        inventory.append(row)

    return authorization_state, inventory, newest, total_bytes


def _authorization_state_fingerprint(
    *,
    claim: Claim,
    document_state: list[dict],
) -> str:
    return _canonical_hash(
        {
            "claim": {
                "id": str(claim.id),
                "status": _enum_value(claim.status),
                "updated_at": _iso(claim.updated_at),
                "deleted_at": _iso(claim.deleted_at),
            },
            "documents": document_state,
        }
    )


def _claim_inventory_row(claim: Claim) -> dict:
    row = {
        "object_kind": "claim",
        "object_id": str(claim.id),
        "status": _enum_value(claim.status),
        "updated_at": _iso(claim.updated_at),
        "deleted_at": _iso(claim.deleted_at),
    }
    row["row_fingerprint"] = _canonical_hash(row)
    return row


def _get_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
) -> DisposalAuthorization:
    stmt = select(DisposalAuthorization).where(
        DisposalAuthorization.id == authorization_id,
        DisposalAuthorization.organization_id == organization_id,
        DisposalAuthorization.claim_id == claim_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    authorization = db.scalar(stmt)
    if authorization is None:
        raise RetentionNotFoundError("Disposal authorization not found")
    return authorization


def _evaluate_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
    now: datetime,
    for_update: bool = False,
) -> _Preflight:
    authorization = _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        authorization_id=authorization_id,
        for_update=for_update,
    )
    if authorization.status != "approved":
        raise DisposalManifestPreflightError(
            outcome="invalidated",
            blocking_reasons=[f"authorization_status_{authorization.status}"],
        )
    if authorization.approved_by_id is None or authorization.approved_at is None:
        raise DisposalManifestPreflightError(
            outcome="invalidated",
            blocking_reasons=["authorization_approval_lineage_incomplete"],
        )
    if now >= _as_utc(authorization.authorization_expires_at):
        raise DisposalManifestPreflightError(
            outcome="expired",
            blocking_reasons=["authorization_expired"],
        )

    claim = get_claim_for_retention(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
    )
    policy = get_current_retention_policy(db, organization_id=organization_id)
    if policy is None:
        raise DisposalManifestPreflightError(
            outcome="invalidated",
            blocking_reasons=["retention_policy_missing_or_disabled"],
        )

    document_state, document_inventory, newest_document_at, total_bytes = (
        _document_state_and_inventory(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
        )
    )
    current_state_fingerprint = _authorization_state_fingerprint(
        claim=claim,
        document_state=document_state,
    )
    claim_anchor = _as_utc(claim.updated_at)
    claim_expires = claim_anchor + timedelta(days=policy.closed_claim_retention_days)
    evidence_anchor = claim_anchor
    if newest_document_at is not None and newest_document_at > evidence_anchor:
        evidence_anchor = newest_document_at
    evidence_expires = evidence_anchor + timedelta(days=policy.evidence_retention_days)

    semantic_drift = any(
        (
            policy.id != authorization.retention_policy_id,
            policy.policy_number != authorization.retention_policy_number,
            policy.policy_hash != authorization.retention_policy_hash,
            claim_anchor != _as_utc(authorization.claim_retention_anchor_at),
            claim_expires != _as_utc(authorization.claim_retention_expires_at),
            evidence_anchor != _as_utc(authorization.evidence_retention_anchor_at),
            evidence_expires != _as_utc(authorization.evidence_retention_expires_at),
            current_state_fingerprint != authorization.state_fingerprint,
        )
    )
    if semantic_drift:
        raise DisposalManifestPreflightError(
            outcome="invalidated",
            blocking_reasons=["authorization_snapshot_drift"],
        )

    eligibility = preview_disposal_eligibility(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        now=now,
    )
    active_hold_ids = [str(item) for item in eligibility.active_hold_ids]
    pending_proposal_ids = [str(item) for item in eligibility.pending_proposal_ids]
    if active_hold_ids:
        raise DisposalManifestPreflightError(
            outcome="blocked",
            blocking_reasons=["active_legal_hold"],
        )
    if pending_proposal_ids:
        raise DisposalManifestPreflightError(
            outcome="blocked",
            blocking_reasons=["pending_legal_hold_proposal"],
        )
    if not eligibility.eligible:
        raise DisposalManifestPreflightError(
            outcome="blocked",
            blocking_reasons=list(eligibility.blocking_reasons),
        )

    inventory = [_claim_inventory_row(claim), *document_inventory]
    inventory_hash = _canonical_hash(inventory)
    return _Preflight(
        authorization=authorization,
        claim=claim,
        policy=policy,
        authorization_lineage_hash=_authorization_lineage_hash(authorization),
        inventory=inventory,
        inventory_hash=inventory_hash,
        document_count=len(document_inventory),
        total_file_size_bytes=total_bytes,
        active_hold_ids=active_hold_ids,
        pending_proposal_ids=pending_proposal_ids,
    )


def _manifest_hash(
    *,
    authorization_id: UUID,
    authorization_lineage_hash: str,
    authorization_snapshot_hash: str,
    authorization_state_fingerprint: str,
    inventory_hash: str,
    retention_policy_id: UUID,
    retention_policy_number: int,
    retention_policy_hash: str,
    evaluated_at: datetime,
    manifest_expires_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "disposal_authorization_id": str(authorization_id),
            "authorization_lineage_hash": authorization_lineage_hash,
            "authorization_snapshot_hash": authorization_snapshot_hash,
            "authorization_state_fingerprint": authorization_state_fingerprint,
            "inventory_hash": inventory_hash,
            "retention_policy_id": str(retention_policy_id),
            "retention_policy_number": retention_policy_number,
            "retention_policy_hash": retention_policy_hash,
            "evaluated_at": _iso(evaluated_at),
            "manifest_expires_at": _iso(manifest_expires_at),
        }
    )


def create_disposal_execution_manifest(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
    created_by_id: UUID,
    now: datetime | None = None,
) -> DisposalExecutionManifest:
    current_time = _as_utc(now or _utc_now())
    existing = db.scalar(
        select(DisposalExecutionManifest).where(
            DisposalExecutionManifest.organization_id == organization_id,
            DisposalExecutionManifest.disposal_authorization_id == authorization_id,
        )
    )
    if existing is not None:
        raise ValueError(
            "An execution manifest already exists for this disposal authorization; "
            "fresh authorization is required for another manifest"
        )

    preflight = _evaluate_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        authorization_id=authorization_id,
        now=current_time,
        for_update=True,
    )
    manifest_expires_at = min(
        current_time + MANIFEST_VALIDITY_WINDOW,
        _as_utc(preflight.authorization.authorization_expires_at),
    )
    manifest_hash = _manifest_hash(
        authorization_id=preflight.authorization.id,
        authorization_lineage_hash=preflight.authorization_lineage_hash,
        authorization_snapshot_hash=preflight.authorization.eligibility_snapshot_hash,
        authorization_state_fingerprint=preflight.authorization.state_fingerprint,
        inventory_hash=preflight.inventory_hash,
        retention_policy_id=preflight.policy.id,
        retention_policy_number=preflight.policy.policy_number,
        retention_policy_hash=preflight.policy.policy_hash,
        evaluated_at=current_time,
        manifest_expires_at=manifest_expires_at,
    )
    manifest = DisposalExecutionManifest(
        organization_id=organization_id,
        claim_id=claim_id,
        disposal_authorization_id=preflight.authorization.id,
        retention_policy_id=preflight.policy.id,
        retention_policy_number=preflight.policy.policy_number,
        retention_policy_hash=preflight.policy.policy_hash,
        authorization_lineage_hash=preflight.authorization_lineage_hash,
        authorization_snapshot_hash=preflight.authorization.eligibility_snapshot_hash,
        authorization_state_fingerprint=preflight.authorization.state_fingerprint,
        authorization_expires_at=preflight.authorization.authorization_expires_at,
        inventory=preflight.inventory,
        inventory_hash=preflight.inventory_hash,
        manifest_hash=manifest_hash,
        document_count=preflight.document_count,
        total_file_size_bytes=preflight.total_file_size_bytes,
        active_hold_ids=preflight.active_hold_ids,
        pending_proposal_ids=preflight.pending_proposal_ids,
        created_by_id=created_by_id,
        evaluated_at=current_time,
        manifest_expires_at=manifest_expires_at,
        last_revalidated_at=current_time,
        status="ready",
    )
    db.add(manifest)
    db.flush()
    return manifest


def list_disposal_execution_manifests(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> list[DisposalExecutionManifest]:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    return list(
        db.scalars(
            select(DisposalExecutionManifest)
            .where(
                DisposalExecutionManifest.organization_id == organization_id,
                DisposalExecutionManifest.claim_id == claim_id,
            )
            .order_by(
                DisposalExecutionManifest.created_at.desc(),
                DisposalExecutionManifest.id.desc(),
            )
        ).all()
    )


def get_disposal_execution_manifest(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    manifest_id: UUID,
    for_update: bool = False,
) -> DisposalExecutionManifest:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    stmt = select(DisposalExecutionManifest).where(
        DisposalExecutionManifest.id == manifest_id,
        DisposalExecutionManifest.organization_id == organization_id,
        DisposalExecutionManifest.claim_id == claim_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    manifest = db.scalar(stmt)
    if manifest is None:
        raise RetentionNotFoundError("Disposal execution manifest not found")
    return manifest


def _terminalize(
    manifest: DisposalExecutionManifest,
    *,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> None:
    manifest.status = status
    manifest.terminal_by_id = actor_id
    manifest.terminal_at = now
    manifest.terminal_reason = reason
    manifest.last_revalidated_at = now


def _stored_manifest_integrity_ok(manifest: DisposalExecutionManifest) -> bool:
    if _canonical_hash(list(manifest.inventory or [])) != manifest.inventory_hash:
        return False
    expected = _manifest_hash(
        authorization_id=manifest.disposal_authorization_id,
        authorization_lineage_hash=manifest.authorization_lineage_hash,
        authorization_snapshot_hash=manifest.authorization_snapshot_hash,
        authorization_state_fingerprint=manifest.authorization_state_fingerprint,
        inventory_hash=manifest.inventory_hash,
        retention_policy_id=manifest.retention_policy_id,
        retention_policy_number=manifest.retention_policy_number,
        retention_policy_hash=manifest.retention_policy_hash,
        evaluated_at=_as_utc(manifest.evaluated_at),
        manifest_expires_at=_as_utc(manifest.manifest_expires_at),
    )
    return expected == manifest.manifest_hash


def revalidate_disposal_execution_manifest(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    manifest_id: UUID,
    actor_id: UUID,
    now: datetime | None = None,
) -> tuple[DisposalExecutionManifest, str]:
    current_time = _as_utc(now or _utc_now())
    manifest = get_disposal_execution_manifest(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        manifest_id=manifest_id,
        for_update=True,
    )
    if manifest.status != "ready":
        return manifest, "unchanged"

    if not _stored_manifest_integrity_ok(manifest):
        _terminalize(
            manifest,
            status="invalidated",
            actor_id=actor_id,
            reason="Stored execution manifest integrity check failed.",
            now=current_time,
        )
        db.flush()
        return manifest, "invalidated"

    if current_time >= _as_utc(manifest.manifest_expires_at):
        _terminalize(
            manifest,
            status="expired",
            actor_id=actor_id,
            reason="Execution manifest validity window expired.",
            now=current_time,
        )
        db.flush()
        return manifest, "expired"

    try:
        preflight = _evaluate_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            authorization_id=manifest.disposal_authorization_id,
            now=current_time,
            for_update=True,
        )
    except DisposalManifestPreflightError as exc:
        _terminalize(
            manifest,
            status=exc.outcome,
            actor_id=actor_id,
            reason="Preflight failed: " + ", ".join(exc.blocking_reasons),
            now=current_time,
        )
        db.flush()
        return manifest, exc.outcome

    drift = any(
        (
            preflight.authorization_lineage_hash != manifest.authorization_lineage_hash,
            preflight.authorization.eligibility_snapshot_hash
            != manifest.authorization_snapshot_hash,
            preflight.authorization.state_fingerprint
            != manifest.authorization_state_fingerprint,
            preflight.policy.id != manifest.retention_policy_id,
            preflight.policy.policy_number != manifest.retention_policy_number,
            preflight.policy.policy_hash != manifest.retention_policy_hash,
            preflight.inventory_hash != manifest.inventory_hash,
            preflight.inventory != list(manifest.inventory or []),
            preflight.active_hold_ids != list(manifest.active_hold_ids or []),
            preflight.pending_proposal_ids != list(manifest.pending_proposal_ids or []),
        )
    )
    if drift:
        _terminalize(
            manifest,
            status="invalidated",
            actor_id=actor_id,
            reason="Authorization, retention, claim, evidence, or storage inventory drift detected.",
            now=current_time,
        )
        db.flush()
        return manifest, "invalidated"

    manifest.last_revalidated_at = current_time
    db.flush()
    return manifest, "ready"

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.retention_disposal_dry_run_models import DisposalDryRunCeremony
from app.modules.claims.retention_disposal_manifest_models import DisposalExecutionManifest
from app.modules.claims.retention_disposal_manifest_service import (
    get_disposal_execution_manifest,
    revalidate_disposal_execution_manifest,
)
from app.modules.claims.retention_service import RetentionNotFoundError, get_claim_for_retention

CEREMONY_VALIDITY_WINDOW = timedelta(minutes=30)


class DisposalDryRunPreflightError(ValueError):
    def __init__(
        self,
        *,
        outcome: str,
        blocking_reasons: list[str],
        manifest_id: UUID | None = None,
        manifest_state_changed: bool = False,
    ):
        self.outcome = outcome
        self.blocking_reasons = list(blocking_reasons)
        self.manifest_id = manifest_id
        self.manifest_state_changed = manifest_state_changed
        super().__init__(
            "Disposal dry-run ceremony preflight failed: "
            + ", ".join(self.blocking_reasons)
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
        raise ValueError("Ceremony reason must contain at least 5 characters")
    if len(normalized) > 2000:
        raise ValueError("Ceremony reason must not exceed 2000 characters")
    return normalized


def _dry_run_plan(manifest: DisposalExecutionManifest) -> list[dict]:
    plan: list[dict] = []
    for sequence, source in enumerate(list(manifest.inventory or []), start=1):
        object_kind = source.get("object_kind")
        if object_kind == "claim":
            row = {
                "sequence": sequence,
                "mode": "dry_run_only",
                "object_kind": "claim",
                "object_id": source.get("object_id"),
                "row_fingerprint": source.get("row_fingerprint"),
                "simulated_action": "database_record_disposal_candidate",
            }
        elif object_kind == "document":
            row = {
                "sequence": sequence,
                "mode": "dry_run_only",
                "object_kind": "document",
                "object_id": source.get("object_id"),
                "row_fingerprint": source.get("row_fingerprint"),
                "file_hash": source.get("file_hash"),
                "storage_key_fingerprint": source.get("storage_key_fingerprint"),
                "file_size_bytes": int(source.get("file_size_bytes") or 0),
                "version_number": source.get("version_number"),
                "is_current": source.get("is_current"),
                "simulated_action": "document_and_storage_disposal_candidate",
            }
        else:
            raise ValueError("Manifest inventory contains an unsupported object kind")
        row["plan_row_hash"] = _canonical_hash(row)
        plan.append(row)
    return plan


def _ceremony_hash(
    *,
    manifest: DisposalExecutionManifest,
    plan_hash: str,
    created_by_id: UUID,
    opening_reason: str,
    opened_at: datetime,
    ceremony_expires_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(manifest.organization_id),
            "claim_id": str(manifest.claim_id),
            "disposal_execution_manifest_id": str(manifest.id),
            "disposal_authorization_id": str(manifest.disposal_authorization_id),
            "retention_policy_id": str(manifest.retention_policy_id),
            "manifest_hash": manifest.manifest_hash,
            "inventory_hash": manifest.inventory_hash,
            "authorization_lineage_hash": manifest.authorization_lineage_hash,
            "retention_policy_number": manifest.retention_policy_number,
            "retention_policy_hash": manifest.retention_policy_hash,
            "plan_hash": plan_hash,
            "created_by_id": str(created_by_id),
            "opening_reason": opening_reason,
            "opened_at": _iso(opened_at),
            "ceremony_expires_at": _iso(ceremony_expires_at),
        }
    )


def _attestation_hash(
    ceremony: DisposalDryRunCeremony,
    *,
    attested_by_id: UUID,
    attested_at: datetime,
    reason: str,
    manifest_last_revalidated_at: datetime | None,
) -> str:
    return _canonical_hash(
        {
            "ceremony_id": str(ceremony.id),
            "ceremony_hash": ceremony.ceremony_hash,
            "manifest_hash": ceremony.manifest_hash,
            "inventory_hash": ceremony.inventory_hash,
            "plan_hash": ceremony.plan_hash,
            "attested_by_id": str(attested_by_id),
            "attested_at": _iso(attested_at),
            "attestation_reason": reason,
            "manifest_last_revalidated_at": _iso(manifest_last_revalidated_at),
            "execution_authority_created": False,
            "destructive_action_performed": False,
        }
    )


def _get_ceremony(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    ceremony_id: UUID,
    for_update: bool = False,
) -> DisposalDryRunCeremony:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    stmt = select(DisposalDryRunCeremony).where(
        DisposalDryRunCeremony.id == ceremony_id,
        DisposalDryRunCeremony.organization_id == organization_id,
        DisposalDryRunCeremony.claim_id == claim_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    ceremony = db.scalar(stmt)
    if ceremony is None:
        raise RetentionNotFoundError("Disposal dry-run ceremony not found")
    return ceremony


def _manifest_failure(
    manifest: DisposalExecutionManifest,
    *,
    revalidation_outcome: str,
) -> DisposalDryRunPreflightError:
    outcome = manifest.status
    if outcome not in {"blocked", "invalidated", "expired"}:
        outcome = "invalidated"
    reason = manifest.terminal_reason or f"manifest_status_{manifest.status}"
    return DisposalDryRunPreflightError(
        outcome=outcome,
        blocking_reasons=[reason],
        manifest_id=manifest.id,
        manifest_state_changed=revalidation_outcome != "unchanged",
    )


def _stored_ceremony_integrity_ok(ceremony: DisposalDryRunCeremony) -> bool:
    if _canonical_hash(list(ceremony.dry_run_plan or [])) != ceremony.plan_hash:
        return False
    manifest_stub = type(
        "ManifestStub",
        (),
        {
            "organization_id": ceremony.organization_id,
            "claim_id": ceremony.claim_id,
            "id": ceremony.disposal_execution_manifest_id,
            "disposal_authorization_id": ceremony.disposal_authorization_id,
            "retention_policy_id": ceremony.retention_policy_id,
            "manifest_hash": ceremony.manifest_hash,
            "inventory_hash": ceremony.inventory_hash,
            "authorization_lineage_hash": ceremony.authorization_lineage_hash,
            "retention_policy_number": ceremony.retention_policy_number,
            "retention_policy_hash": ceremony.retention_policy_hash,
        },
    )()
    expected = _ceremony_hash(
        manifest=manifest_stub,
        plan_hash=ceremony.plan_hash,
        created_by_id=ceremony.created_by_id,
        opening_reason=ceremony.opening_reason,
        opened_at=_as_utc(ceremony.opened_at),
        ceremony_expires_at=_as_utc(ceremony.ceremony_expires_at),
    )
    return expected == ceremony.ceremony_hash


def open_disposal_dry_run_ceremony(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    manifest_id: UUID,
    created_by_id: UUID,
    opening_reason: str,
    now: datetime | None = None,
) -> DisposalDryRunCeremony:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(opening_reason)
    existing = db.scalar(
        select(DisposalDryRunCeremony).where(
            DisposalDryRunCeremony.organization_id == organization_id,
            DisposalDryRunCeremony.disposal_execution_manifest_id == manifest_id,
        )
    )
    if existing is not None:
        raise ValueError(
            "A dry-run ceremony already exists for this execution manifest; "
            "fresh authorization and manifest are required for another ceremony"
        )

    manifest, revalidation_outcome = revalidate_disposal_execution_manifest(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        manifest_id=manifest_id,
        actor_id=created_by_id,
        now=current_time,
    )
    if manifest.status != "ready":
        raise _manifest_failure(manifest, revalidation_outcome=revalidation_outcome)

    plan = _dry_run_plan(manifest)
    plan_hash = _canonical_hash(plan)
    ceremony_expires_at = min(
        current_time + CEREMONY_VALIDITY_WINDOW,
        _as_utc(manifest.manifest_expires_at),
    )
    if ceremony_expires_at <= current_time:
        raise DisposalDryRunPreflightError(
            outcome="expired",
            blocking_reasons=["manifest_expired_before_ceremony_open"],
            manifest_id=manifest.id,
            manifest_state_changed=False,
        )
    ceremony_hash = _ceremony_hash(
        manifest=manifest,
        plan_hash=plan_hash,
        created_by_id=created_by_id,
        opening_reason=reason,
        opened_at=current_time,
        ceremony_expires_at=ceremony_expires_at,
    )
    ceremony = DisposalDryRunCeremony(
        organization_id=organization_id,
        claim_id=claim_id,
        disposal_execution_manifest_id=manifest.id,
        disposal_authorization_id=manifest.disposal_authorization_id,
        retention_policy_id=manifest.retention_policy_id,
        manifest_hash=manifest.manifest_hash,
        inventory_hash=manifest.inventory_hash,
        authorization_lineage_hash=manifest.authorization_lineage_hash,
        retention_policy_number=manifest.retention_policy_number,
        retention_policy_hash=manifest.retention_policy_hash,
        manifest_expires_at=manifest.manifest_expires_at,
        dry_run_plan=plan,
        plan_hash=plan_hash,
        ceremony_hash=ceremony_hash,
        document_count=manifest.document_count,
        total_file_size_bytes=manifest.total_file_size_bytes,
        created_by_id=created_by_id,
        opening_reason=reason,
        opened_at=current_time,
        ceremony_expires_at=ceremony_expires_at,
        last_revalidated_at=current_time,
        status="pending_attestation",
    )
    db.add(ceremony)
    db.flush()
    return ceremony


def list_disposal_dry_run_ceremonies(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> list[DisposalDryRunCeremony]:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    return list(
        db.scalars(
            select(DisposalDryRunCeremony)
            .where(
                DisposalDryRunCeremony.organization_id == organization_id,
                DisposalDryRunCeremony.claim_id == claim_id,
            )
            .order_by(
                DisposalDryRunCeremony.created_at.desc(),
                DisposalDryRunCeremony.id.desc(),
            )
        ).all()
    )


def get_disposal_dry_run_ceremony(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    ceremony_id: UUID,
) -> DisposalDryRunCeremony:
    return _get_ceremony(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        ceremony_id=ceremony_id,
    )


def _terminalize(
    ceremony: DisposalDryRunCeremony,
    *,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> None:
    ceremony.status = status
    ceremony.terminal_by_id = actor_id
    ceremony.terminal_at = now
    ceremony.terminal_reason = reason
    ceremony.last_revalidated_at = now


def attest_disposal_dry_run_ceremony(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    ceremony_id: UUID,
    attested_by_id: UUID,
    attestation_reason: str,
    now: datetime | None = None,
) -> tuple[DisposalDryRunCeremony, str]:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(attestation_reason)
    ceremony = _get_ceremony(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        ceremony_id=ceremony_id,
        for_update=True,
    )
    if ceremony.status != "pending_attestation":
        return ceremony, "unchanged"
    if ceremony.created_by_id == attested_by_id:
        raise ValueError("Ceremony creator cannot attest their own dry run")
    if current_time >= _as_utc(ceremony.ceremony_expires_at):
        _terminalize(
            ceremony,
            status="expired",
            actor_id=attested_by_id,
            reason="Dry-run ceremony validity window expired.",
            now=current_time,
        )
        db.flush()
        return ceremony, "expired"
    if not _stored_ceremony_integrity_ok(ceremony):
        _terminalize(
            ceremony,
            status="invalidated",
            actor_id=attested_by_id,
            reason="Stored dry-run ceremony integrity check failed.",
            now=current_time,
        )
        db.flush()
        return ceremony, "invalidated"

    manifest, manifest_outcome = revalidate_disposal_execution_manifest(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        manifest_id=ceremony.disposal_execution_manifest_id,
        actor_id=attested_by_id,
        now=current_time,
    )
    if manifest.status != "ready":
        mapped = manifest.status if manifest.status in {"blocked", "invalidated", "expired"} else "invalidated"
        _terminalize(
            ceremony,
            status=mapped,
            actor_id=attested_by_id,
            reason=manifest.terminal_reason or f"Execution manifest became {manifest.status}.",
            now=current_time,
        )
        db.flush()
        return ceremony, mapped

    live_plan = _dry_run_plan(manifest)
    live_plan_hash = _canonical_hash(live_plan)
    drift = any(
        (
            manifest.id != ceremony.disposal_execution_manifest_id,
            manifest.disposal_authorization_id != ceremony.disposal_authorization_id,
            manifest.retention_policy_id != ceremony.retention_policy_id,
            manifest.manifest_hash != ceremony.manifest_hash,
            manifest.inventory_hash != ceremony.inventory_hash,
            manifest.authorization_lineage_hash != ceremony.authorization_lineage_hash,
            manifest.retention_policy_number != ceremony.retention_policy_number,
            manifest.retention_policy_hash != ceremony.retention_policy_hash,
            manifest.document_count != ceremony.document_count,
            manifest.total_file_size_bytes != ceremony.total_file_size_bytes,
            live_plan_hash != ceremony.plan_hash,
            live_plan != list(ceremony.dry_run_plan or []),
        )
    )
    if drift:
        _terminalize(
            ceremony,
            status="invalidated",
            actor_id=attested_by_id,
            reason="Manifest or dry-run plan drift detected during independent attestation.",
            now=current_time,
        )
        db.flush()
        return ceremony, "invalidated"

    ceremony.status = "attested"
    ceremony.attested_by_id = attested_by_id
    ceremony.attested_at = current_time
    ceremony.attestation_reason = reason
    ceremony.attestation_hash = _attestation_hash(
        ceremony,
        attested_by_id=attested_by_id,
        attested_at=current_time,
        reason=reason,
        manifest_last_revalidated_at=manifest.last_revalidated_at,
    )
    ceremony.last_revalidated_at = current_time
    db.flush()
    return ceremony, "attested"


def cancel_disposal_dry_run_ceremony(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    ceremony_id: UUID,
    cancelled_by_id: UUID,
    cancellation_reason: str,
    now: datetime | None = None,
) -> tuple[DisposalDryRunCeremony, str]:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(cancellation_reason)
    ceremony = _get_ceremony(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        ceremony_id=ceremony_id,
        for_update=True,
    )
    if ceremony.status != "pending_attestation":
        return ceremony, "unchanged"
    if current_time >= _as_utc(ceremony.ceremony_expires_at):
        _terminalize(
            ceremony,
            status="expired",
            actor_id=cancelled_by_id,
            reason="Dry-run ceremony validity window expired before cancellation.",
            now=current_time,
        )
        db.flush()
        return ceremony, "expired"
    _terminalize(
        ceremony,
        status="cancelled",
        actor_id=cancelled_by_id,
        reason=reason,
        now=current_time,
    )
    db.flush()
    return ceremony, "cancelled"

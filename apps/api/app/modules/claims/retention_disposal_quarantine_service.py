import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.retention_disposal_dry_run_models import DisposalDryRunCeremony
from app.modules.claims.retention_disposal_dry_run_service import (
    _as_utc,
    _attestation_hash,
    _canonical_hash,
    _dry_run_plan,
    _stored_ceremony_integrity_ok,
)
from app.modules.claims.retention_disposal_manifest_models import DisposalExecutionManifest
from app.modules.claims.retention_disposal_manifest_service import (
    revalidate_disposal_execution_manifest,
)
from app.modules.claims.retention_disposal_quarantine_models import DisposalQuarantineStage
from app.modules.claims.retention_service import RetentionNotFoundError, get_claim_for_retention

QUARANTINE_STAGE_WINDOW = timedelta(minutes=15)


class DisposalQuarantinePreflightError(ValueError):
    def __init__(
        self,
        *,
        outcome: str,
        blocking_reasons: list[str],
        ceremony_id: UUID | None = None,
        manifest_id: UUID | None = None,
        manifest_state_changed: bool = False,
    ):
        self.outcome = outcome
        self.blocking_reasons = list(blocking_reasons)
        self.ceremony_id = ceremony_id
        self.manifest_id = manifest_id
        self.manifest_state_changed = manifest_state_changed
        super().__init__(
            "Disposal quarantine staging preflight failed: "
            + ", ".join(self.blocking_reasons)
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _as_utc(value).isoformat()


def _normalize_reason(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < 5:
        raise ValueError("Quarantine stage reason must contain at least 5 characters")
    if len(normalized) > 2000:
        raise ValueError("Quarantine stage reason must not exceed 2000 characters")
    return normalized


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


def _get_stage(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    stage_id: UUID,
    for_update: bool = False,
) -> DisposalQuarantineStage:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    stmt = select(DisposalQuarantineStage).where(
        DisposalQuarantineStage.id == stage_id,
        DisposalQuarantineStage.organization_id == organization_id,
        DisposalQuarantineStage.claim_id == claim_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    stage = db.scalar(stmt)
    if stage is None:
        raise RetentionNotFoundError("Disposal quarantine stage not found")
    return stage


def _attestation_integrity_ok(ceremony: DisposalDryRunCeremony) -> bool:
    if ceremony.status != "attested":
        return False
    if (
        ceremony.attested_by_id is None
        or ceremony.attested_at is None
        or ceremony.attestation_hash is None
        or ceremony.attestation_reason is None
        or ceremony.last_revalidated_at is None
    ):
        return False
    expected = _attestation_hash(
        ceremony,
        attested_by_id=ceremony.attested_by_id,
        attested_at=_as_utc(ceremony.attested_at),
        reason=ceremony.attestation_reason,
        manifest_last_revalidated_at=_as_utc(ceremony.last_revalidated_at),
    )
    return expected == ceremony.attestation_hash


def _overlay_plan(ceremony: DisposalDryRunCeremony) -> list[dict]:
    overlay: list[dict] = []
    for source in list(ceremony.dry_run_plan or []):
        row = {
            "sequence": source.get("sequence"),
            "mode": "logical_quarantine_overlay",
            "object_kind": source.get("object_kind"),
            "object_id": source.get("object_id"),
            "row_fingerprint": source.get("row_fingerprint"),
            "overlay_action": "governance_quarantine_marker_only",
            "physical_mutation_performed": False,
        }
        if source.get("object_kind") == "document":
            row.update(
                {
                    "file_hash": source.get("file_hash"),
                    "storage_key_fingerprint": source.get("storage_key_fingerprint"),
                    "file_size_bytes": int(source.get("file_size_bytes") or 0),
                    "version_number": source.get("version_number"),
                    "is_current": source.get("is_current"),
                }
            )
        elif source.get("object_kind") != "claim":
            raise ValueError("Dry-run plan contains an unsupported object kind")
        row["overlay_row_hash"] = _canonical_hash(row)
        overlay.append(row)
    return overlay


def _stage_hash(
    *,
    ceremony: DisposalDryRunCeremony,
    overlay_hash: str,
    staged_by_id: UUID,
    staging_reason: str,
    staged_at: datetime,
    stage_expires_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(ceremony.organization_id),
            "claim_id": str(ceremony.claim_id),
            "disposal_dry_run_ceremony_id": str(ceremony.id),
            "disposal_execution_manifest_id": str(ceremony.disposal_execution_manifest_id),
            "disposal_authorization_id": str(ceremony.disposal_authorization_id),
            "retention_policy_id": str(ceremony.retention_policy_id),
            "manifest_hash": ceremony.manifest_hash,
            "inventory_hash": ceremony.inventory_hash,
            "authorization_lineage_hash": ceremony.authorization_lineage_hash,
            "ceremony_hash": ceremony.ceremony_hash,
            "plan_hash": ceremony.plan_hash,
            "attestation_hash": ceremony.attestation_hash,
            "retention_policy_number": ceremony.retention_policy_number,
            "retention_policy_hash": ceremony.retention_policy_hash,
            "overlay_hash": overlay_hash,
            "staged_by_id": str(staged_by_id),
            "staging_reason": staging_reason,
            "staged_at": _iso(staged_at),
            "stage_expires_at": _iso(stage_expires_at),
            "logical_overlay_only": True,
            "physical_quarantine_performed": False,
            "destructive_action_performed": False,
        }
    )


def _stored_stage_integrity_ok(stage: DisposalQuarantineStage) -> bool:
    if _canonical_hash(list(stage.overlay_plan or [])) != stage.overlay_hash:
        return False
    ceremony_stub = type(
        "CeremonyStub",
        (),
        {
            "organization_id": stage.organization_id,
            "claim_id": stage.claim_id,
            "id": stage.disposal_dry_run_ceremony_id,
            "disposal_execution_manifest_id": stage.disposal_execution_manifest_id,
            "disposal_authorization_id": stage.disposal_authorization_id,
            "retention_policy_id": stage.retention_policy_id,
            "manifest_hash": stage.manifest_hash,
            "inventory_hash": stage.inventory_hash,
            "authorization_lineage_hash": stage.authorization_lineage_hash,
            "ceremony_hash": stage.ceremony_hash,
            "plan_hash": stage.plan_hash,
            "attestation_hash": stage.attestation_hash,
            "retention_policy_number": stage.retention_policy_number,
            "retention_policy_hash": stage.retention_policy_hash,
        },
    )()
    expected = _stage_hash(
        ceremony=ceremony_stub,
        overlay_hash=stage.overlay_hash,
        staged_by_id=stage.staged_by_id,
        staging_reason=stage.staging_reason,
        staged_at=_as_utc(stage.staged_at),
        stage_expires_at=_as_utc(stage.stage_expires_at),
    )
    return expected == stage.stage_hash


def _validate_live_attested_ceremony(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    ceremony: DisposalDryRunCeremony,
    actor_id: UUID,
    now: datetime,
) -> tuple[DisposalExecutionManifest, list[dict], str]:
    if ceremony.status != "attested":
        raise DisposalQuarantinePreflightError(
            outcome="invalidated",
            blocking_reasons=[f"dry_run_ceremony_status_{ceremony.status}"],
            ceremony_id=ceremony.id,
            manifest_id=ceremony.disposal_execution_manifest_id,
        )
    if now >= _as_utc(ceremony.ceremony_expires_at):
        raise DisposalQuarantinePreflightError(
            outcome="expired",
            blocking_reasons=["dry_run_ceremony_expired"],
            ceremony_id=ceremony.id,
            manifest_id=ceremony.disposal_execution_manifest_id,
        )
    if not _stored_ceremony_integrity_ok(ceremony):
        raise DisposalQuarantinePreflightError(
            outcome="invalidated",
            blocking_reasons=["stored_dry_run_ceremony_integrity_failed"],
            ceremony_id=ceremony.id,
            manifest_id=ceremony.disposal_execution_manifest_id,
        )
    if not _attestation_integrity_ok(ceremony):
        raise DisposalQuarantinePreflightError(
            outcome="invalidated",
            blocking_reasons=["dry_run_attestation_integrity_failed"],
            ceremony_id=ceremony.id,
            manifest_id=ceremony.disposal_execution_manifest_id,
        )

    manifest, revalidation_outcome = revalidate_disposal_execution_manifest(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        manifest_id=ceremony.disposal_execution_manifest_id,
        actor_id=actor_id,
        now=now,
    )
    if manifest.status != "ready":
        mapped = (
            manifest.status
            if manifest.status in {"blocked", "invalidated", "expired"}
            else "invalidated"
        )
        raise DisposalQuarantinePreflightError(
            outcome=mapped,
            blocking_reasons=[
                manifest.terminal_reason or f"execution_manifest_status_{manifest.status}"
            ],
            ceremony_id=ceremony.id,
            manifest_id=manifest.id,
            manifest_state_changed=revalidation_outcome != "unchanged",
        )

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
        raise DisposalQuarantinePreflightError(
            outcome="invalidated",
            blocking_reasons=["manifest_or_dry_run_plan_drift"],
            ceremony_id=ceremony.id,
            manifest_id=manifest.id,
            manifest_state_changed=revalidation_outcome != "unchanged",
        )
    return manifest, live_plan, revalidation_outcome


def create_disposal_quarantine_stage(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    ceremony_id: UUID,
    staged_by_id: UUID,
    staging_reason: str,
    now: datetime | None = None,
) -> DisposalQuarantineStage:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(staging_reason)
    ceremony = _get_ceremony(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        ceremony_id=ceremony_id,
        for_update=True,
    )
    existing = db.scalar(
        select(DisposalQuarantineStage).where(
            DisposalQuarantineStage.organization_id == organization_id,
            DisposalQuarantineStage.disposal_dry_run_ceremony_id == ceremony_id,
        )
    )
    if existing is not None:
        raise ValueError(
            "A quarantine stage already exists for this dry-run ceremony; "
            "fresh authorization, manifest, and ceremony are required for another stage"
        )

    _manifest, _live_plan, _outcome = _validate_live_attested_ceremony(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        ceremony=ceremony,
        actor_id=staged_by_id,
        now=current_time,
    )
    overlay = _overlay_plan(ceremony)
    overlay_hash = _canonical_hash(overlay)
    stage_expires_at = min(
        current_time + QUARANTINE_STAGE_WINDOW,
        _as_utc(ceremony.ceremony_expires_at),
    )
    if stage_expires_at <= current_time:
        raise DisposalQuarantinePreflightError(
            outcome="expired",
            blocking_reasons=["dry_run_ceremony_expired_before_quarantine_stage"],
            ceremony_id=ceremony.id,
            manifest_id=ceremony.disposal_execution_manifest_id,
        )
    stage_hash = _stage_hash(
        ceremony=ceremony,
        overlay_hash=overlay_hash,
        staged_by_id=staged_by_id,
        staging_reason=reason,
        staged_at=current_time,
        stage_expires_at=stage_expires_at,
    )
    stage = DisposalQuarantineStage(
        organization_id=organization_id,
        claim_id=claim_id,
        disposal_dry_run_ceremony_id=ceremony.id,
        disposal_execution_manifest_id=ceremony.disposal_execution_manifest_id,
        disposal_authorization_id=ceremony.disposal_authorization_id,
        retention_policy_id=ceremony.retention_policy_id,
        manifest_hash=ceremony.manifest_hash,
        inventory_hash=ceremony.inventory_hash,
        authorization_lineage_hash=ceremony.authorization_lineage_hash,
        ceremony_hash=ceremony.ceremony_hash,
        plan_hash=ceremony.plan_hash,
        attestation_hash=ceremony.attestation_hash,
        retention_policy_number=ceremony.retention_policy_number,
        retention_policy_hash=ceremony.retention_policy_hash,
        ceremony_expires_at=ceremony.ceremony_expires_at,
        overlay_plan=overlay,
        overlay_hash=overlay_hash,
        stage_hash=stage_hash,
        document_count=ceremony.document_count,
        total_file_size_bytes=ceremony.total_file_size_bytes,
        staged_by_id=staged_by_id,
        staging_reason=reason,
        staged_at=current_time,
        stage_expires_at=stage_expires_at,
        last_revalidated_at=current_time,
        status="staged",
    )
    db.add(stage)
    db.flush()
    return stage


def list_disposal_quarantine_stages(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> list[DisposalQuarantineStage]:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    return list(
        db.scalars(
            select(DisposalQuarantineStage)
            .where(
                DisposalQuarantineStage.organization_id == organization_id,
                DisposalQuarantineStage.claim_id == claim_id,
            )
            .order_by(
                DisposalQuarantineStage.created_at.desc(),
                DisposalQuarantineStage.id.desc(),
            )
        ).all()
    )


def get_disposal_quarantine_stage(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    stage_id: UUID,
) -> DisposalQuarantineStage:
    return _get_stage(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        stage_id=stage_id,
    )


def _terminalize(
    stage: DisposalQuarantineStage,
    *,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> None:
    stage.status = status
    stage.terminal_by_id = actor_id
    stage.terminal_at = now
    stage.terminal_reason = reason
    stage.last_revalidated_at = now


def _revalidate_loaded_stage(
    db: Session,
    *,
    stage: DisposalQuarantineStage,
    actor_id: UUID,
    now: datetime,
) -> str:
    if stage.status != "staged":
        return "unchanged"
    if now >= _as_utc(stage.stage_expires_at):
        _terminalize(
            stage,
            status="expired",
            actor_id=actor_id,
            reason="Logical quarantine stage validity window expired.",
            now=now,
        )
        db.flush()
        return "expired"
    if not _stored_stage_integrity_ok(stage):
        _terminalize(
            stage,
            status="invalidated",
            actor_id=actor_id,
            reason="Stored logical quarantine stage integrity check failed.",
            now=now,
        )
        db.flush()
        return "invalidated"

    ceremony = _get_ceremony(
        db,
        organization_id=stage.organization_id,
        claim_id=stage.claim_id,
        ceremony_id=stage.disposal_dry_run_ceremony_id,
    )
    try:
        _manifest, _live_plan, _manifest_outcome = _validate_live_attested_ceremony(
            db,
            organization_id=stage.organization_id,
            claim_id=stage.claim_id,
            ceremony=ceremony,
            actor_id=actor_id,
            now=now,
        )
    except DisposalQuarantinePreflightError as exc:
        mapped = exc.outcome if exc.outcome in {"expired", "invalidated"} else "invalidated"
        _terminalize(
            stage,
            status=mapped,
            actor_id=actor_id,
            reason="; ".join(exc.blocking_reasons),
            now=now,
        )
        db.flush()
        return mapped

    live_overlay = _overlay_plan(ceremony)
    live_overlay_hash = _canonical_hash(live_overlay)
    drift = any(
        (
            ceremony.id != stage.disposal_dry_run_ceremony_id,
            ceremony.disposal_execution_manifest_id != stage.disposal_execution_manifest_id,
            ceremony.disposal_authorization_id != stage.disposal_authorization_id,
            ceremony.retention_policy_id != stage.retention_policy_id,
            ceremony.manifest_hash != stage.manifest_hash,
            ceremony.inventory_hash != stage.inventory_hash,
            ceremony.authorization_lineage_hash != stage.authorization_lineage_hash,
            ceremony.ceremony_hash != stage.ceremony_hash,
            ceremony.plan_hash != stage.plan_hash,
            ceremony.attestation_hash != stage.attestation_hash,
            ceremony.retention_policy_number != stage.retention_policy_number,
            ceremony.retention_policy_hash != stage.retention_policy_hash,
            ceremony.document_count != stage.document_count,
            ceremony.total_file_size_bytes != stage.total_file_size_bytes,
            live_overlay_hash != stage.overlay_hash,
            live_overlay != list(stage.overlay_plan or []),
        )
    )
    if drift:
        _terminalize(
            stage,
            status="invalidated",
            actor_id=actor_id,
            reason="Quarantine overlay lineage drift detected.",
            now=now,
        )
        db.flush()
        return "invalidated"

    stage.last_revalidated_at = now
    db.flush()
    return "revalidated"


def revalidate_disposal_quarantine_stage(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    stage_id: UUID,
    actor_id: UUID,
    now: datetime | None = None,
) -> tuple[DisposalQuarantineStage, str]:
    current_time = _as_utc(now or _utc_now())
    stage = _get_stage(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        stage_id=stage_id,
        for_update=True,
    )
    outcome = _revalidate_loaded_stage(
        db,
        stage=stage,
        actor_id=actor_id,
        now=current_time,
    )
    return stage, outcome


def restore_disposal_quarantine_stage(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    stage_id: UUID,
    restored_by_id: UUID,
    restoration_reason: str,
    now: datetime | None = None,
) -> tuple[DisposalQuarantineStage, str]:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(restoration_reason)
    stage = _get_stage(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        stage_id=stage_id,
        for_update=True,
    )
    if stage.status != "staged":
        return stage, "unchanged"
    outcome = _revalidate_loaded_stage(
        db,
        stage=stage,
        actor_id=restored_by_id,
        now=current_time,
    )
    if outcome in {"expired", "invalidated"}:
        return stage, outcome
    stage.status = "restored"
    stage.restored_by_id = restored_by_id
    stage.restored_at = current_time
    stage.restoration_reason = reason
    stage.last_revalidated_at = current_time
    db.flush()
    return stage, "restored"


def cancel_disposal_quarantine_stage(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    stage_id: UUID,
    cancelled_by_id: UUID,
    cancellation_reason: str,
    now: datetime | None = None,
) -> tuple[DisposalQuarantineStage, str]:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(cancellation_reason)
    stage = _get_stage(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        stage_id=stage_id,
        for_update=True,
    )
    if stage.status != "staged":
        return stage, "unchanged"
    outcome = _revalidate_loaded_stage(
        db,
        stage=stage,
        actor_id=cancelled_by_id,
        now=current_time,
    )
    if outcome in {"expired", "invalidated"}:
        return stage, outcome
    _terminalize(
        stage,
        status="cancelled",
        actor_id=cancelled_by_id,
        reason=reason,
        now=current_time,
    )
    db.flush()
    return stage, "cancelled"

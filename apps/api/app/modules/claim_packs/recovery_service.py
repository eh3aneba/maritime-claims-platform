from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claim_packs.models import ClaimPackExport, ClaimPackFormat
from app.modules.claim_packs.recovery_renderers import render_pdf, render_xlsx
from app.modules.claim_packs.recovery_snapshot import build_recovery_snapshot
from app.modules.claim_packs.service import (
    _jsonable,
    _safe_reference,
    _snapshot_hash,
    build_claim_pack_snapshot as _base_snapshot,
    get_claim_pack_export,
    list_claim_pack_exports,
)
from app.modules.claims.service import get_claim
from app.modules.documents.service import _storage
from app.modules.users.models import User


SNAPSHOT_SCHEMA_VERSION = "1.2"


def build_claim_pack_snapshot(
    db: Session,
    *,
    claim,
    user: User,
    generation_note: str | None,
    generated_at: datetime,
) -> dict:
    snapshot = _base_snapshot(
        db,
        claim=claim,
        user=user,
        generation_note=generation_note,
        generated_at=generated_at,
    )
    recovery = _jsonable(build_recovery_snapshot(db, claim=claim))
    summary = recovery["summary"]
    snapshot["snapshot_schema_version"] = SNAPSHOT_SCHEMA_VERSION
    snapshot["recovery_review"] = recovery
    snapshot["summary"].update(
        {
            "recovery_human_closure_review_state": recovery["human_closure_review_state"],
            "recovery_counterparty_count": summary["counterparty_count"],
            "recovery_timebar_scenario_count": summary["timebar_scenario_count"],
            "recovery_human_decision_count": summary["human_decision_count"],
            "recovery_human_action_count": summary["human_action_count"],
            "recovery_open_human_decision_count": summary["open_human_decision_count"],
            "recovery_stale_human_decision_count": summary["stale_human_decision_count"],
            "recovery_unreviewed_counterparty_count": summary["unreviewed_counterparty_count"],
            "recovery_stale_timebar_scenario_count": summary["stale_timebar_scenario_count"],
            "recovery_unreviewed_timebar_scenario_count": summary["unreviewed_timebar_scenario_count"],
        }
    )
    if recovery["human_closure_review_state"] == "attention_required":
        snapshot["summary"]["review_state"] = "attention_required"
    elif (
        recovery["human_closure_review_state"] == "open_recovery_paths"
        and snapshot["summary"]["review_state"] == "reviewed"
    ):
        snapshot["summary"]["review_state"] = "reviewed_with_open_items"
    return snapshot


def generate_claim_pack(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
    user: User,
    export_format: ClaimPackFormat,
    generation_note: str | None,
) -> ClaimPackExport:
    claim = get_claim(db, claim_id=claim_id, organization_id=organization_id)
    generated_at = datetime.now(UTC)
    note = generation_note.strip() if generation_note and generation_note.strip() else None
    snapshot = build_claim_pack_snapshot(
        db,
        claim=claim,
        user=user,
        generation_note=note,
        generated_at=generated_at,
    )
    snapshot_hash = _snapshot_hash(snapshot)
    if export_format == ClaimPackFormat.PDF:
        payload = render_pdf(snapshot)
        mime_type = "application/pdf"
        suffix = "pdf"
    else:
        payload = render_xlsx(snapshot)
        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        suffix = "xlsx"

    export_id = uuid4()
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    filename = f"{_safe_reference(claim.claim_reference)}-claim-pack-{timestamp}.{suffix}"
    storage_key = f"claim-pack-exports/{organization_id}/{claim.id}/{export_id}/{filename}"
    stored = _storage().save_bytes(payload, storage_key)
    record = ClaimPackExport(
        id=export_id,
        organization_id=organization_id,
        claim_id=claim.id,
        generated_by_id=user.id,
        export_format=export_format,
        snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
        snapshot=snapshot,
        snapshot_hash=snapshot_hash,
        generation_note=note,
        filename=filename,
        mime_type=mime_type,
        storage_key=storage_key,
        file_hash=stored.file_hash,
        file_size_bytes=stored.file_size_bytes,
    )
    try:
        db.add(record)
        db.flush()
        write_audit_log(
            db,
            organization_id=organization_id,
            user_id=user.id,
            action="GENERATE_CLAIM_PACK_EXPORT",
            entity_type="claim_pack_export",
            entity_id=record.id,
            new_values={
                "claim_id": str(claim.id),
                "format": export_format.value,
                "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
                "snapshot_hash": snapshot_hash,
                "file_hash": stored.file_hash,
                "review_state": snapshot["summary"]["review_state"],
                "recovery_human_closure_review_state": snapshot["summary"]["recovery_human_closure_review_state"],
                "recovery_human_decision_count": snapshot["summary"]["recovery_human_decision_count"],
                "recovery_human_action_count": snapshot["summary"]["recovery_human_action_count"],
            },
            details="Generated immutable controlled claim-pack snapshot with downstream recovery/time-bar human-record projection.",
        )
        db.commit()
        db.refresh(record)
        return record
    except Exception:
        db.rollback()
        _storage().delete_physical(storage_key)
        raise


__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "build_claim_pack_snapshot",
    "generate_claim_pack",
    "get_claim_pack_export",
    "list_claim_pack_exports",
]

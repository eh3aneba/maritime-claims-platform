from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_read_ownership_transition_authorization_service import (
    RecoveryReadOwnershipTransitionAuthorizationConflict,
    RecoveryReadOwnershipTransitionAuthorizationNotFound,
    RecoveryReadOwnershipTransitionAuthorizationUnavailable,
    _get_authorization,
)
from app.modules.documents.recovery_read_ownership_transition_routing_service import (
    RecoveryReadOwnershipTransitionRoutingConflict,
    RecoveryReadOwnershipTransitionRoutingError,
    RecoveryReadOwnershipTransitionRoutingNotFound,
    RecoveryReadOwnershipTransitionRoutingUnavailable,
    _approval_receipt,
    _fresh_source_and_candidate_proof,
    _get_lease,
    _utc_now,
)
from app.modules.documents.recovery_replication_service import (
    RecoveryReplicationConflict,
    RecoveryReplicationUnavailable,
)
from app.modules.documents.recovery_routable_read_cutover_service import (
    RecoveryRoutableReadCutoverConflict,
    RecoveryRoutableReadCutoverNotFound,
    RecoveryRoutableReadCutoverUnavailable,
    _get_route,
)


def _authorization_matches_lease(authorization, lease) -> bool:
    return all(
        (
            authorization.id == lease.authorization_id,
            authorization.status == "approved",
            authorization.approved_by_id == lease.authorization_approved_by_id,
            authorization.authorization_hash == lease.authorization_hash,
            authorization.request_snapshot_hash == lease.authorization_request_snapshot_hash,
            authorization.integrity_proof_hash == lease.authorization_integrity_proof_hash,
            authorization.phase_t_health_qualification_id == lease.phase_t_health_qualification_id,
            authorization.phase_t_health_qualification_hash == lease.phase_t_health_qualification_hash,
            authorization.operational_evidence_hash == lease.operational_evidence_hash,
            authorization.replica_id == lease.replica_id,
            authorization.replica_hash == lease.replica_hash,
            authorization.source_file_hash == lease.source_file_hash,
            authorization.source_file_size_bytes == lease.source_file_size_bytes,
            authorization.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            authorization.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            authorization.candidate_storage_key_fingerprint == lease.candidate_storage_key_fingerprint,
            authorization.source_authority_fingerprint == lease.source_authority_fingerprint,
            authorization.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            authorization.configuration_fingerprint == lease.configuration_fingerprint,
            authorization.verified_durable_read_count == lease.verified_durable_read_count,
            authorization.integrity_failure_count == lease.integrity_failure_count,
            authorization.storage_unavailable_count == lease.storage_unavailable_count,
            authorization.route_expired_attempt_count == lease.route_expired_attempt_count,
            authorization.operational_event_count == lease.operational_event_count,
            authorization.route_version_at_request == lease.route_version_at_prepare,
            authorization.routable_authority_created is False,
            authorization.durable_read_route_created is False,
            authorization.read_path_switched is False,
            authorization.write_path_switched is False,
            authorization.document_storage_key_mutated is False,
            authorization.authoritative_storage_changed is False,
            authorization.destructive_action_performed is False,
            authorization.s3_delete_performed is False,
            authorization.local_delete_performed is False,
        )
    )


def resolve_recovery_document_read_ownership_transition(
    db: Session,
    *,
    document: Document,
    now: datetime | None = None,
) -> tuple[bytes, str]:
    current_time = _as_utc(now or _utc_now())
    try:
        route = _get_route(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
        )
        assert route is not None
        if (
            route.route_authority_kind != "read_ownership_transition"
            or route.active_read_ownership_transition_lease_id is None
        ):
            raise RecoveryReadOwnershipTransitionRoutingNotFound(
                "No active Phase V read-ownership transition route exists"
            )
        lease = _get_lease(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            lease_id=route.active_read_ownership_transition_lease_id,
        )
        if lease.status != "activated" or lease.route_expires_at is None:
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase V read authority is not active"
            )
        if current_time >= _as_utc(lease.route_expires_at):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase V read-ownership route expired; reconciliation or rollback is required"
            )
        if not all(
            (
                route.route_class == "recovery_replica",
                route.route_authority_kind == "read_ownership_transition",
                route.durable_authority_active is True,
                route.active_lease_id is None,
                route.active_durable_lease_id is None,
                route.active_durable_renewal_lease_id is None,
                route.active_durable_reauthorized_renewal_lease_id is None,
                route.active_read_ownership_transition_lease_id == lease.id,
                route.active_replica_id == lease.replica_id,
                route.route_version == lease.route_version_at_prepare + 1,
                route.source_authority_fingerprint == lease.source_authority_fingerprint,
                route.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
                route.configuration_fingerprint == lease.configuration_fingerprint,
                route.read_path_switched is True,
                route.write_path_switched is False,
                route.document_storage_key_mutated is False,
                route.authoritative_storage_changed is False,
                route.destructive_action_performed is False,
                lease.routable_authority_created is True,
                lease.durable_read_route_created is True,
                lease.read_ownership_authority_created is True,
                lease.read_path_switched is True,
                lease.write_path_switched is False,
                lease.document_storage_key_mutated is False,
                lease.authoritative_storage_changed is False,
                lease.destructive_action_performed is False,
                lease.s3_delete_performed is False,
                lease.local_delete_performed is False,
            )
        ):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase V shared read-route binding drifted"
            )
        authorization = _get_authorization(
            db,
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            authorization_id=lease.authorization_id,
        )
        if not _authorization_matches_lease(authorization, lease):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase U authorization lineage drifted while Phase V owned reads"
            )
        approval = _approval_receipt(db, authorization=authorization)
        if (
            approval.id != lease.authorization_approval_receipt_id
            or approval.receipt_hash != lease.authorization_approval_receipt_hash
        ):
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase U approval receipt drifted while Phase V owned reads"
            )
        integrity_proof_hash, payload = _fresh_source_and_candidate_proof(
            db, authorization=authorization
        )
        if integrity_proof_hash != lease.integrity_proof_hash:
            raise RecoveryReadOwnershipTransitionRoutingConflict(
                "Phase V fresh integrity proof no longer matches the prepared lease"
            )
        return payload, "recovery-replica-read-ownership-transition"
    except RecoveryReadOwnershipTransitionRoutingError:
        raise
    except RecoveryReadOwnershipTransitionAuthorizationNotFound as exc:
        raise RecoveryReadOwnershipTransitionRoutingNotFound(str(exc)) from exc
    except RecoveryReadOwnershipTransitionAuthorizationConflict as exc:
        raise RecoveryReadOwnershipTransitionRoutingConflict(str(exc)) from exc
    except RecoveryReadOwnershipTransitionAuthorizationUnavailable as exc:
        raise RecoveryReadOwnershipTransitionRoutingUnavailable(str(exc)) from exc
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise RecoveryReadOwnershipTransitionRoutingNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryReadOwnershipTransitionRoutingConflict(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryReadOwnershipTransitionRoutingUnavailable(str(exc)) from exc

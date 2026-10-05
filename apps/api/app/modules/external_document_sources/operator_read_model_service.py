from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.models import ExternalDocumentSourceProfile
from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionExecution,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
)
from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
    ExternalDocumentSourceObservationReviewDecision,
)
from app.modules.external_document_sources.observation_review_handoff_models import (
    ExternalDocumentSourceObservationReviewHandoff,
)
from app.modules.external_document_sources.operator_baseline_integrity import (
    baseline_transition_is_integrity_valid,
)
from app.modules.external_document_sources.operator_read_model_schemas import (
    ExternalDocumentSourceOperatorFamilyRead,
    ExternalDocumentSourceOperatorOverviewRead,
    ExternalDocumentSourceOperatorProfileRead,
    ExternalDocumentSourceOperatorVersionRead,
)
from app.modules.external_document_sources.processing_release_models import (
    ExternalDocumentSourceProcessingRelease,
)
from app.modules.external_document_sources.provider_client_health_models import (
    ExternalDocumentSourceProviderClientHealthExecution,
)
from app.modules.external_document_sources.recurring_baseline_transition_models import (
    ExternalDocumentSourceRecurringBaselineTransition,
    ExternalDocumentSourceRecurringBaselineTransitionReceipt,
)
from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
)
from app.modules.external_document_sources.sftp_credential_health_models import (
    ExternalDocumentSourceSftpCredentialHealthQualification,
)
from app.modules.external_document_sources.sftp_session_activation_models import (
    ExternalDocumentSourceSftpSessionActivation,
)
from app.modules.external_document_sources.sftp_transport_verification_models import (
    ExternalDocumentSourceSftpTransportVerification,
)


_REFRESH_FAILURE_AUDIT_ACTION = "EXTERNAL_EVIDENCE_OBSERVATION_REFRESH_FAILED"


def _latest_by(rows, key, timestamp):
    result = {}
    for row in rows:
        row_key = key(row)
        current = result.get(row_key)
        row_time = timestamp(row)
        current_time = timestamp(current) if current is not None else None
        if current is None or (
            row_time is not None
            and (current_time is None or row_time > current_time)
        ):
            result[row_key] = row
    return result


def _latest_sftp_rows_by_profile(
    db: Session,
    *,
    model: Any,
    organization_id: UUID,
    profile_ids: list[UUID],
    timestamp_column: Any,
) -> dict[UUID, Any]:
    """Return one deterministic latest row per profile without loading history."""

    if not profile_ids:
        return {}

    ranked = (
        select(
            model.id.label("row_id"),
            func.row_number()
            .over(
                partition_by=model.profile_id,
                order_by=(timestamp_column.desc(), model.id.desc()),
            )
            .label("row_rank"),
        )
        .where(
            model.organization_id == organization_id,
            model.profile_id.in_(profile_ids),
        )
        .subquery()
    )
    rows = list(
        db.scalars(
            select(model)
            .join(ranked, model.id == ranked.c.row_id)
            .where(ranked.c.row_rank == 1)
        ).all()
    )
    return {row.profile_id: row for row in rows}


def _sftp_current_lineage_rows(
    *,
    profile_hash: str,
    credential_health: Any | None,
    transport_verification: Any | None,
    session_activation: Any | None,
) -> tuple[Any | None, Any | None, Any | None]:
    credential_current = (
        credential_health is not None
        and credential_health.profile_hash == profile_hash
    )
    transport_current = (
        transport_verification is not None
        and transport_verification.profile_hash == profile_hash
    )
    session_current = (
        session_activation is not None
        and session_activation.profile_hash == profile_hash
        and credential_current
        and transport_current
        and session_activation.health_qualification_id == credential_health.id
        and session_activation.transport_verification_id == transport_verification.id
    )
    return (
        credential_health if credential_current else None,
        transport_verification if transport_current else None,
        session_activation if session_current else None,
    )


def _sftp_runtime_readiness(
    *,
    profile_hash: str,
    credential_health: Any | None,
    transport_verification: Any | None,
    session_activation: Any | None,
) -> str:
    credential_health, transport_verification, session_activation = (
        _sftp_current_lineage_rows(
            profile_hash=profile_hash,
            credential_health=credential_health,
            transport_verification=transport_verification,
            session_activation=session_activation,
        )
    )
    statuses = (
        credential_health.result_status if credential_health is not None else None,
        transport_verification.result_status
        if transport_verification is not None
        else None,
        session_activation.result_status if session_activation is not None else None,
    )
    if statuses == ("qualified", "verified", "activated"):
        return "ready"
    if any(
        status in {"unqualified", "failed"}
        for status in statuses
        if status is not None
    ):
        return "attention"
    return "not_qualified"


def _current_document_reference(
    *,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    family_documents: list[Document],
    admission: ExternalDocumentSourceObservationRefreshAdmissionExecution | None,
) -> tuple[UUID, int]:
    current_candidates = [row for row in family_documents if row.is_current]
    if len(current_candidates) == 1:
        current_document = current_candidates[0]
        return current_document.id, current_document.version_number
    if admission is not None:
        return admission.new_document_id, admission.new_version_number
    return binding.current_document_id, binding.current_version_number


def _integrity_valid_current_baselines(
    db: Session,
    *,
    organization_id: UUID,
    bindings: list[ExternalDocumentSourceEvidenceFamilyBinding],
    current_reference_by_binding: dict[UUID, tuple[UUID, int]],
) -> dict[tuple[UUID, UUID, int], ExternalDocumentSourceRecurringBaselineTransition]:
    """Read only current SFTP baseline candidates and validate them in bounded batches."""

    sftp_bindings = [row for row in bindings if row.provider_kind == "sftp"]
    if not sftp_bindings:
        return {}
    binding_by_id = {row.id: row for row in sftp_bindings}
    binding_ids = list(binding_by_id)
    current_document_ids = [
        current_reference_by_binding[binding_id][0]
        for binding_id in binding_ids
        if binding_id in current_reference_by_binding
    ]
    if not current_document_ids:
        return {}

    candidates = list(
        db.scalars(
            select(ExternalDocumentSourceRecurringBaselineTransition).where(
                ExternalDocumentSourceRecurringBaselineTransition.organization_id
                == organization_id,
                ExternalDocumentSourceRecurringBaselineTransition.binding_id.in_(
                    binding_ids
                ),
                ExternalDocumentSourceRecurringBaselineTransition.current_document_id.in_(
                    current_document_ids
                ),
                ExternalDocumentSourceRecurringBaselineTransition.status == "established",
            )
        ).all()
    )
    if not candidates:
        return {}

    candidate_ids = [row.id for row in candidates]
    receipts = list(
        db.scalars(
            select(ExternalDocumentSourceRecurringBaselineTransitionReceipt).where(
                ExternalDocumentSourceRecurringBaselineTransitionReceipt.organization_id
                == organization_id,
                ExternalDocumentSourceRecurringBaselineTransitionReceipt.transition_id.in_(
                    candidate_ids
                ),
            )
        ).all()
    )
    receipts_by_transition: dict[
        UUID, list[ExternalDocumentSourceRecurringBaselineTransitionReceipt]
    ] = defaultdict(list)
    for receipt in receipts:
        receipts_by_transition[receipt.transition_id].append(receipt)

    valid: dict[
        tuple[UUID, UUID, int], ExternalDocumentSourceRecurringBaselineTransition
    ] = {}
    for transition in candidates:
        binding = binding_by_id.get(transition.binding_id)
        if binding is None:
            continue
        expected_reference = current_reference_by_binding.get(binding.id)
        if expected_reference != (
            transition.current_document_id,
            transition.current_version_number,
        ):
            continue
        if not baseline_transition_is_integrity_valid(
            binding=binding,
            transition=transition,
            receipts=receipts_by_transition.get(transition.id, []),
        ):
            continue
        valid[
            (
                transition.binding_id,
                transition.current_document_id,
                transition.current_version_number,
            )
        ] = transition
    return valid


def build_external_document_source_operator_overview(
    db: Session,
    *,
    organization_id: UUID,
) -> ExternalDocumentSourceOperatorOverviewRead:
    """Compose durable facts into a non-authoritative, DB-only operator view.

    No provider network, secret-resolution or storage I/O is performed here. Every
    mutation shown by the UI continues to call its dedicated governed phase API.
    """

    profiles = list(
        db.scalars(
            select(ExternalDocumentSourceProfile)
            .where(ExternalDocumentSourceProfile.organization_id == organization_id)
            .order_by(ExternalDocumentSourceProfile.display_name.asc())
        ).all()
    )
    bindings = list(
        db.scalars(
            select(ExternalDocumentSourceEvidenceFamilyBinding).where(
                ExternalDocumentSourceEvidenceFamilyBinding.organization_id
                == organization_id,
                ExternalDocumentSourceEvidenceFamilyBinding.status == "active",
            )
        ).all()
    )
    health_rows = list(
        db.scalars(
            select(ExternalDocumentSourceProviderClientHealthExecution).where(
                ExternalDocumentSourceProviderClientHealthExecution.organization_id
                == organization_id
            )
        ).all()
    )
    schedules = list(
        db.scalars(
            select(ExternalDocumentSourceRecurringObservationSchedule).where(
                ExternalDocumentSourceRecurringObservationSchedule.organization_id
                == organization_id
            )
        ).all()
    )
    observations = list(
        db.scalars(
            select(ExternalDocumentSourceDueTickObservationExecution).where(
                ExternalDocumentSourceDueTickObservationExecution.organization_id
                == organization_id
            )
        ).all()
    )
    handoffs = list(
        db.scalars(
            select(ExternalDocumentSourceObservationReviewHandoff).where(
                ExternalDocumentSourceObservationReviewHandoff.organization_id
                == organization_id
            )
        ).all()
    )
    decisions = list(
        db.scalars(
            select(ExternalDocumentSourceObservationReviewDecision).where(
                ExternalDocumentSourceObservationReviewDecision.organization_id
                == organization_id
            )
        ).all()
    )
    refresh_authorizations = list(
        db.scalars(
            select(ExternalDocumentSourceObservationRefreshAuthorization).where(
                ExternalDocumentSourceObservationRefreshAuthorization.organization_id
                == organization_id
            )
        ).all()
    )
    refreshes = list(
        db.scalars(
            select(ExternalDocumentSourceObservationRefreshExecution).where(
                ExternalDocumentSourceObservationRefreshExecution.organization_id
                == organization_id
            )
        ).all()
    )
    admission_authorizations = list(
        db.scalars(
            select(ExternalDocumentSourceObservationRefreshAdmissionAuthorization).where(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorization.organization_id
                == organization_id
            )
        ).all()
    )
    admissions = list(
        db.scalars(
            select(ExternalDocumentSourceObservationRefreshAdmissionExecution).where(
                ExternalDocumentSourceObservationRefreshAdmissionExecution.organization_id
                == organization_id
            )
        ).all()
    )
    releases = list(
        db.scalars(
            select(ExternalDocumentSourceProcessingRelease).where(
                ExternalDocumentSourceProcessingRelease.organization_id
                == organization_id
            )
        ).all()
    )

    sftp_profile_ids = [
        profile.id for profile in profiles if profile.provider_kind == "sftp"
    ]
    latest_sftp_credential_health = _latest_sftp_rows_by_profile(
        db,
        model=ExternalDocumentSourceSftpCredentialHealthQualification,
        organization_id=organization_id,
        profile_ids=sftp_profile_ids,
        timestamp_column=ExternalDocumentSourceSftpCredentialHealthQualification.checked_at,
    )
    latest_sftp_transport = _latest_sftp_rows_by_profile(
        db,
        model=ExternalDocumentSourceSftpTransportVerification,
        organization_id=organization_id,
        profile_ids=sftp_profile_ids,
        timestamp_column=ExternalDocumentSourceSftpTransportVerification.checked_at,
    )
    latest_sftp_session = _latest_sftp_rows_by_profile(
        db,
        model=ExternalDocumentSourceSftpSessionActivation,
        organization_id=organization_id,
        profile_ids=sftp_profile_ids,
        timestamp_column=ExternalDocumentSourceSftpSessionActivation.checked_at,
    )

    family_ids = [binding.document_family_id for binding in bindings]
    documents = (
        list(
            db.scalars(
                select(Document)
                .where(
                    Document.organization_id == organization_id,
                    Document.document_family_id.in_(family_ids),
                    Document.deleted_at.is_(None),
                )
                .order_by(
                    Document.document_family_id.asc(),
                    Document.version_number.asc(),
                )
            ).all()
        )
        if family_ids
        else []
    )
    refresh_failure_audits = list(
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == organization_id,
                AuditLog.action == _REFRESH_FAILURE_AUDIT_ACTION,
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )

    latest_health = _latest_by(
        health_rows, lambda row: row.profile_id, lambda row: row.completed_at
    )
    latest_schedule = _latest_by(
        schedules,
        lambda row: row.binding_id,
        lambda row: row.authorized_at if row.status == "active" else row.disabled_at,
    )
    latest_observation = _latest_by(
        observations,
        lambda row: row.binding_id,
        lambda row: row.completed_at,
    )
    latest_decision = _latest_by(
        decisions, lambda row: row.binding_id, lambda row: row.decided_at
    )
    latest_refresh_authorization = _latest_by(
        refresh_authorizations,
        lambda row: row.binding_id,
        lambda row: row.authorized_at,
    )
    latest_refresh = _latest_by(
        refreshes, lambda row: row.binding_id, lambda row: row.completed_at
    )
    latest_admission_auth = _latest_by(
        admission_authorizations,
        lambda row: row.binding_id,
        lambda row: row.authorized_at,
    )
    latest_admission = _latest_by(
        admissions, lambda row: row.binding_id, lambda row: row.executed_at
    )

    decided_handoffs = {row.handoff_id for row in decisions}
    pending_handoffs = [row for row in handoffs if row.id not in decided_handoffs]
    latest_pending_handoff = _latest_by(
        pending_handoffs,
        lambda row: row.binding_id,
        lambda row: row.projected_at,
    )

    documents_by_family: dict[UUID, list[Document]] = defaultdict(list)
    for document in documents:
        documents_by_family[document.document_family_id].append(document)

    current_reference_by_binding: dict[UUID, tuple[UUID, int]] = {}
    for binding in bindings:
        current_reference_by_binding[binding.id] = _current_document_reference(
            binding=binding,
            family_documents=documents_by_family.get(binding.document_family_id, []),
            admission=latest_admission.get(binding.id),
        )

    release_by_exact_version = {
        (row.binding_id, row.document_id, row.document_version_number): row
        for row in releases
    }
    baseline_transition_by_exact_version = _integrity_valid_current_baselines(
        db,
        organization_id=organization_id,
        bindings=bindings,
        current_reference_by_binding=current_reference_by_binding,
    )

    refresh_authorization_by_id = {row.id: row for row in refresh_authorizations}
    latest_failure_by_binding: dict[UUID, AuditLog] = {}
    for audit in refresh_failure_audits:
        authorization_id = audit.entity_id
        authorization = (
            refresh_authorization_by_id.get(authorization_id)
            if authorization_id is not None
            else None
        )
        if authorization is None:
            continue
        latest_failure_by_binding[authorization.binding_id] = audit

    family_rows: list[ExternalDocumentSourceOperatorFamilyRead] = []
    for binding in bindings:
        schedule = latest_schedule.get(binding.id)
        observation = latest_observation.get(binding.id)
        handoff = latest_pending_handoff.get(binding.id)
        decision = latest_decision.get(binding.id)
        refresh_authorization = latest_refresh_authorization.get(binding.id)
        refresh = latest_refresh.get(binding.id)
        admission_auth = latest_admission_auth.get(binding.id)
        admission = latest_admission.get(binding.id)
        refresh_failure = latest_failure_by_binding.get(binding.id)

        refresh_authorization_is_current = (
            decision is not None
            and decision.decision_kind == "approve_refresh"
            and refresh_authorization is not None
            and refresh_authorization.decision_id == decision.id
        )
        refresh_matches_current_authorization = (
            refresh_authorization_is_current
            and refresh_authorization is not None
            and refresh is not None
            and refresh.authorization_id == refresh_authorization.id
        )
        refresh_execution_required = (
            refresh_authorization_is_current
            and not refresh_matches_current_authorization
        )
        admission_authorization_required = (
            refresh_matches_current_authorization
            and refresh is not None
            and (
                admission_auth is None
                or admission_auth.refresh_execution_id != refresh.id
            )
        )
        admission_auth_matches_current_refresh = (
            refresh_matches_current_authorization
            and refresh is not None
            and admission_auth is not None
            and admission_auth.refresh_execution_id == refresh.id
        )
        admission_execution_required = (
            admission_auth_matches_current_refresh
            and admission_auth is not None
            and (
                admission is None
                or admission.authorization_id != admission_auth.id
            )
        )

        current_document_id, current_version_number = current_reference_by_binding[
            binding.id
        ]
        release = release_by_exact_version.get(
            (binding.id, current_document_id, current_version_number)
        )
        release_status = release.status if release is not None else None
        release_required = release is None or release.status != "active"
        baseline_transition = baseline_transition_by_exact_version.get(
            (binding.id, current_document_id, current_version_number)
        )
        baseline_transition_required = (
            binding.provider_kind == "sftp"
            and current_version_number > 1
            and baseline_transition is None
        )

        family_documents = documents_by_family.get(binding.document_family_id, [])
        version_history: list[ExternalDocumentSourceOperatorVersionRead] = []
        for document in family_documents:
            version_release = release_by_exact_version.get(
                (binding.id, document.id, document.version_number)
            )
            version_release_status = (
                version_release.status if version_release is not None else None
            )
            version_history.append(
                ExternalDocumentSourceOperatorVersionRead(
                    document_id=document.id,
                    version_number=document.version_number,
                    is_current=document.is_current,
                    processing_status=document.processing_status.value,
                    created_at=document.created_at,
                    superseded_at=document.superseded_at,
                    processing_release_status=version_release_status,
                    processing_release_required=(
                        version_release is None or version_release.status != "active"
                    ),
                )
            )

        failure_values = (
            refresh_failure.new_values
            if refresh_failure is not None
            and isinstance(refresh_failure.new_values, dict)
            else {}
        )
        failure_code = failure_values.get("failure_code")
        if not isinstance(failure_code, str):
            failure_code = None

        family_rows.append(
            ExternalDocumentSourceOperatorFamilyRead(
                binding_id=binding.id,
                claim_id=binding.claim_id,
                profile_id=binding.profile_id,
                provider_kind=binding.provider_kind,
                document_family_id=binding.document_family_id,
                current_document_id=current_document_id,
                current_version_number=current_version_number,
                version_history=version_history,
                schedule_id=schedule.id if schedule is not None else None,
                schedule_status=schedule.status if schedule is not None else None,
                next_due_at=(
                    schedule.next_due_at
                    if schedule is not None and schedule.status == "active"
                    else None
                ),
                last_observation_id=observation.id if observation is not None else None,
                last_observation_result=(
                    observation.result_status if observation is not None else None
                ),
                last_observation_completed_at=(
                    observation.completed_at if observation is not None else None
                ),
                pending_handoff_id=handoff.id if handoff is not None else None,
                pending_handoff_kind=(
                    handoff.result_status if handoff is not None else None
                ),
                pending_handoff_projected_at=(
                    handoff.projected_at if handoff is not None else None
                ),
                latest_decision_id=decision.id if decision is not None else None,
                latest_decision_kind=(
                    decision.decision_kind if decision is not None else None
                ),
                latest_decision_status=decision.status if decision is not None else None,
                latest_decided_at=decision.decided_at if decision is not None else None,
                refresh_authorization_id=(
                    refresh_authorization.id
                    if refresh_authorization is not None
                    else None
                ),
                refresh_authorization_status=(
                    refresh_authorization.status
                    if refresh_authorization is not None
                    else None
                ),
                refresh_execution_required=refresh_execution_required,
                latest_refresh_execution_id=refresh.id if refresh is not None else None,
                latest_refresh_status=(
                    refresh.result_status if refresh is not None else None
                ),
                latest_refresh_completed_at=(
                    refresh.completed_at if refresh is not None else None
                ),
                latest_refresh_failure_code=failure_code,
                latest_refresh_failed_at=(
                    refresh_failure.created_at if refresh_failure is not None else None
                ),
                latest_admission_authorization_id=(
                    admission_auth.id if admission_auth is not None else None
                ),
                latest_admission_authorization_status=(
                    admission_auth.status if admission_auth is not None else None
                ),
                admission_authorization_required=admission_authorization_required,
                latest_admission_execution_id=(
                    admission.id if admission is not None else None
                ),
                admission_execution_required=admission_execution_required,
                latest_admission_status=(
                    admission.status if admission is not None else None
                ),
                latest_admission_executed_at=(
                    admission.executed_at if admission is not None else None
                ),
                processing_release_status=release_status,
                processing_release_required=release_required,
                baseline_transition_id=(
                    baseline_transition.id if baseline_transition is not None else None
                ),
                baseline_transition_status=(
                    baseline_transition.status
                    if baseline_transition is not None
                    else None
                ),
                baseline_transition_version_number=(
                    baseline_transition.current_version_number
                    if baseline_transition is not None
                    else None
                ),
                baseline_transition_authorized_at=(
                    baseline_transition.authorized_at
                    if baseline_transition is not None
                    else None
                ),
                baseline_transition_required=baseline_transition_required,
            )
        )

    families_by_profile = defaultdict(list)
    for family in family_rows:
        families_by_profile[family.profile_id].append(family)

    profile_rows: list[ExternalDocumentSourceOperatorProfileRead] = []
    for profile in profiles:
        health = latest_health.get(profile.id)
        raw_sftp_credential_health = latest_sftp_credential_health.get(profile.id)
        raw_sftp_transport = latest_sftp_transport.get(profile.id)
        raw_sftp_session = latest_sftp_session.get(profile.id)
        if profile.provider_kind == "sftp":
            (
                sftp_credential_health,
                sftp_transport,
                sftp_session,
            ) = _sftp_current_lineage_rows(
                profile_hash=profile.profile_hash,
                credential_health=raw_sftp_credential_health,
                transport_verification=raw_sftp_transport,
                session_activation=raw_sftp_session,
            )
            sftp_runtime_readiness = _sftp_runtime_readiness(
                profile_hash=profile.profile_hash,
                credential_health=raw_sftp_credential_health,
                transport_verification=raw_sftp_transport,
                session_activation=raw_sftp_session,
            )
        else:
            sftp_credential_health = None
            sftp_transport = None
            sftp_session = None
            sftp_runtime_readiness = None

        families = families_by_profile.get(profile.id, [])
        due_values = [
            row.next_due_at for row in families if row.next_due_at is not None
        ]
        observation_values = [
            row.last_observation_completed_at
            for row in families
            if row.last_observation_completed_at is not None
        ]
        profile_rows.append(
            ExternalDocumentSourceOperatorProfileRead(
                profile_id=profile.id,
                provider_kind=profile.provider_kind,
                display_name=profile.display_name,
                profile_status=profile.status,
                provider_health_status=(
                    health.result_status if health is not None else None
                ),
                provider_health_latency_class=(
                    health.latency_class if health is not None else None
                ),
                provider_health_completed_at=(
                    health.completed_at if health is not None else None
                ),
                sftp_runtime_readiness=sftp_runtime_readiness,
                sftp_credential_health_status=(
                    sftp_credential_health.result_status
                    if sftp_credential_health is not None
                    else None
                ),
                sftp_credential_health_checked_at=(
                    sftp_credential_health.checked_at
                    if sftp_credential_health is not None
                    else None
                ),
                sftp_transport_status=(
                    sftp_transport.result_status if sftp_transport is not None else None
                ),
                sftp_transport_checked_at=(
                    sftp_transport.checked_at if sftp_transport is not None else None
                ),
                sftp_session_status=(
                    sftp_session.result_status if sftp_session is not None else None
                ),
                sftp_session_checked_at=(
                    sftp_session.checked_at if sftp_session is not None else None
                ),
                active_family_count=len(families),
                pending_handoff_count=sum(
                    1 for row in families if row.pending_handoff_id is not None
                ),
                processing_release_required_count=sum(
                    1 for row in families if row.processing_release_required
                ),
                next_due_at=min(due_values) if due_values else None,
                last_observation_completed_at=(
                    max(observation_values) if observation_values else None
                ),
            )
        )

    return ExternalDocumentSourceOperatorOverviewRead(
        profiles=profile_rows,
        families=family_rows,
    )

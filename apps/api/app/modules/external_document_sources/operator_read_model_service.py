from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
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
from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
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


def build_external_document_source_operator_overview(
    db: Session,
    *,
    organization_id: UUID,
) -> ExternalDocumentSourceOperatorOverviewRead:
    """Compose existing durable facts into a non-authoritative operator view.

    The read model never mutates upstream state and never infers permission for a
    later phase. Every action shown by the UI still calls its governed phase API.
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

    release_by_exact_version = {
        (row.binding_id, row.document_id, row.document_version_number): row
        for row in releases
    }

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

        family_documents = documents_by_family.get(binding.document_family_id, [])
        current_candidates = [row for row in family_documents if row.is_current]
        if len(current_candidates) == 1:
            current_document = current_candidates[0]
            current_document_id = current_document.id
            current_version_number = current_document.version_number
        elif admission is not None:
            current_document_id = admission.new_document_id
            current_version_number = admission.new_version_number
        else:
            current_document_id = binding.current_document_id
            current_version_number = binding.current_version_number

        release = release_by_exact_version.get(
            (binding.id, current_document_id, current_version_number)
        )
        release_status = release.status if release is not None else None
        release_required = release is None or release.status != "active"

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
            )
        )

    families_by_profile = defaultdict(list)
    for family in family_rows:
        families_by_profile[family.profile_id].append(family)

    profile_rows: list[ExternalDocumentSourceOperatorProfileRead] = []
    for profile in profiles:
        health = latest_health.get(profile.id)
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

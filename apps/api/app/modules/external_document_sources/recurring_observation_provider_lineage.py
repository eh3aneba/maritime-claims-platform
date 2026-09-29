from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources import change_detection_service as generic_change
from app.modules.external_document_sources import sftp_change_detection_service as sftp_change
from app.modules.external_document_sources.evidence_admission_execution_models import (
    ExternalDocumentSourceEvidenceAdmissionExecution,
)
from app.modules.external_document_sources.evidence_admission_execution_service import (
    _ensure_execution_integrity as _ensure_legacy_admission_integrity,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    _ensure_binding_integrity,
    _stable_sftp_source_item_hash,
)
from app.modules.external_document_sources.generation_3_change_detection_models import (
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
)
from app.modules.external_document_sources.generation_3_change_detection_service import (
    _checkpoint_generation_3,
    _ensure_integrity as _ensure_legacy_generation3_integrity,
    _lineage as _legacy_generation3_lineage,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_service import (
    _ensure_integrity as _ensure_sftp_authorization_integrity,
)
from app.modules.external_document_sources.sftp_evidence_admission_execution_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionExecution,
)
from app.modules.external_document_sources.sftp_evidence_admission_execution_service import (
    _ensure_execution_integrity as _ensure_sftp_execution_integrity,
)
from app.modules.external_document_sources.sftp_generation3_change_detection_models import (
    ExternalDocumentSourceSftpGeneration3ChangeDetection,
)
from app.modules.external_document_sources.sftp_generation3_change_detection_service import (
    _ensure_integrity as _ensure_sftp_generation3_integrity,
    _load_lineage as _load_sftp_generation3_lineage,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_service import (
    _ensure_integrity as _ensure_sftp_checkpoint_integrity,
)


@dataclass(frozen=True)
class RecurringProviderLineage:
    provider_kind: str
    profile_hash: str
    stable_source_item_hash: str

    legacy_observation_id: UUID | None
    legacy_checkpoint_id: UUID | None
    sftp_observation_id: UUID | None
    sftp_checkpoint_id: UUID | None

    observation_operation_kind: str
    policy_hash: str

    legacy_profile: Any | None = None
    legacy_locator: Any | None = None
    legacy_policy: Any | None = None

    sftp_request: sftp_change.SftpExactFileMetadataRequest | None = None
    sftp_expected_auth_kind: str | None = None
    sftp_display_name_hash: str | None = None


@dataclass(frozen=True)
class RecurringMetadataObservation:
    result_status: str
    observed_projection_hash: str | None
    observed_display_name_hash: str | None
    observed_version_token_hash: str | None
    observed_byte_size: int | None
    observed_modified_at: datetime | None
    observed_mime_type_class: str | None
    observation_adapter_kind: str
    policy_hash: str


def _resolve_legacy(
    db: Session,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
) -> RecurringProviderLineage:
    if (
        binding.provider_kind not in {"sharepoint", "google_drive"}
        or binding.admission_execution_id is None
        or binding.sftp_admission_execution_id is not None
    ):
        raise ExternalDocumentSourceConflictError(
            "Legacy recurring provider-lineage selector drifted"
        )

    admission = db.scalar(
        select(ExternalDocumentSourceEvidenceAdmissionExecution).where(
            ExternalDocumentSourceEvidenceAdmissionExecution.id
            == binding.admission_execution_id,
            ExternalDocumentSourceEvidenceAdmissionExecution.organization_id
            == binding.organization_id,
            ExternalDocumentSourceEvidenceAdmissionExecution.profile_id
            == binding.profile_id,
        )
    )
    if admission is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation initial admission lineage is missing"
        )
    _ensure_legacy_admission_integrity(db, admission)

    observation = db.scalar(
        select(ExternalDocumentSourceGeneration3ChangeDetectionExecution).where(
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.id
            == admission.generation_3_change_detection_execution_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.organization_id
            == binding.organization_id,
            ExternalDocumentSourceGeneration3ChangeDetectionExecution.profile_id
            == binding.profile_id,
        )
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "Recurring observation provider-lineage observation is missing"
        )
    _ensure_legacy_generation3_integrity(db, observation)
    if (
        observation.status != "completed"
        or observation.result_status != "unchanged"
        or observation.observed_provider_item_id_hash
        != binding.stable_source_item_hash
        or observation.observed_projection_hash != binding.source_projection_hash
        or observation.completion_hash
        != binding.source_observation_completion_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring observation provider lineage drifted"
        )

    checkpoint = _checkpoint_generation_3(
        db,
        organization_id=binding.organization_id,
        profile_id=binding.profile_id,
        execution_id=observation.checkpoint_generation_3_execution_id,
    )
    (
        _candidate,
        _phase_s_observation,
        _listing,
        item,
        profile,
        locator,
        policy,
        _baseline,
        _baseline_hash,
    ) = _legacy_generation3_lineage(db, checkpoint)

    if (
        profile.profile_hash != binding.profile_hash
        or profile.provider_kind != binding.provider_kind
        or hashlib.sha256(item.provider_item_id.encode("utf-8")).hexdigest()
        != binding.stable_source_item_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Recurring observation exact-item provider lineage drifted"
        )

    return RecurringProviderLineage(
        provider_kind=binding.provider_kind,
        profile_hash=binding.profile_hash,
        stable_source_item_hash=binding.stable_source_item_hash,
        legacy_observation_id=observation.id,
        legacy_checkpoint_id=checkpoint.id,
        sftp_observation_id=None,
        sftp_checkpoint_id=None,
        observation_operation_kind=policy.observation_operation_kind,
        policy_hash=generic_change._endpoint_policy_hash(policy),
        legacy_profile=profile,
        legacy_locator=locator,
        legacy_policy=policy,
    )


def _resolve_sftp(
    db: Session,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
) -> RecurringProviderLineage:
    if (
        binding.provider_kind != "sftp"
        or binding.admission_execution_id is not None
        or binding.sftp_admission_execution_id is None
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP recurring provider-lineage selector drifted"
        )

    execution = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionExecution).where(
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.id
            == binding.sftp_admission_execution_id,
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.organization_id
            == binding.organization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionExecution.profile_id
            == binding.profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP recurring admission execution lineage is missing"
        )
    _ensure_sftp_execution_integrity(db, execution)

    authorization = db.scalar(
        select(ExternalDocumentSourceSftpEvidenceAdmissionAuthorization).where(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.id
            == execution.authorization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.organization_id
            == binding.organization_id,
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.profile_id
            == binding.profile_id,
        )
    )
    if authorization is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP recurring admission authorization lineage is missing"
        )
    _ensure_sftp_authorization_integrity(db, authorization)

    observation = db.scalar(
        select(ExternalDocumentSourceSftpGeneration3ChangeDetection).where(
            ExternalDocumentSourceSftpGeneration3ChangeDetection.id
            == execution.generation3_change_detection_id,
            ExternalDocumentSourceSftpGeneration3ChangeDetection.organization_id
            == binding.organization_id,
            ExternalDocumentSourceSftpGeneration3ChangeDetection.profile_id
            == binding.profile_id,
        )
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP recurring generation-3 observation lineage is missing"
        )
    _ensure_sftp_generation3_integrity(db, observation)

    checkpoint = db.scalar(
        select(ExternalDocumentSourceSftpGeneration3CheckpointAdvancement).where(
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.id
            == execution.generation3_checkpoint_advancement_id,
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.organization_id
            == binding.organization_id,
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.profile_id
            == binding.profile_id,
        )
    )
    if checkpoint is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP recurring generation-3 checkpoint lineage is missing"
        )
    _ensure_sftp_checkpoint_integrity(db, checkpoint)

    (
        _candidate,
        _predecessor_observation,
        listing,
        entry,
        credential_binding,
        normalized,
        checkpoint_baseline_projection_hash,
    ) = _load_sftp_generation3_lineage(db, checkpoint)

    expected_source_hash = _stable_sftp_source_item_hash(
        profile_id=binding.profile_id,
        relative_path_hash=authorization.authorized_relative_path_hash,
    )
    if (
        execution.authorization_id != authorization.id
        or execution.generation3_change_detection_id != authorization.generation3_change_detection_id
        or execution.generation3_checkpoint_advancement_id
        != authorization.generation3_checkpoint_advancement_id
        or observation.id != authorization.generation3_change_detection_id
        or checkpoint.id != authorization.generation3_checkpoint_advancement_id
        or observation.generation3_checkpoint_advancement_id != checkpoint.id
        or observation.result_status != "unchanged"
        or observation.provider_kind != "sftp"
        or observation.profile_hash != binding.profile_hash
        or observation.observed_projection_hash != binding.source_projection_hash
        or observation.completion_hash != binding.source_observation_completion_hash
        or observation.baseline_relative_path_hash
        != authorization.authorized_relative_path_hash
        or sftp_change._relative_path_hash(entry.relative_path)
        != authorization.authorized_relative_path_hash
        or expected_source_hash != binding.stable_source_item_hash
        or checkpoint_baseline_projection_hash != observation.baseline_projection_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP recurring provider lineage drifted"
        )

    adapter = sftp_change._METADATA_ADAPTER
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter is unavailable"
        )
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if (
        not isinstance(adapter_kind, str)
        or not sftp_change._SAFE_ADAPTER_KIND.fullmatch(adapter_kind)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP exact-file metadata adapter kind is invalid"
        )

    request = sftp_change.SftpExactFileMetadataRequest(
        hostname=listing.destination_hostname,
        port=listing.destination_port,
        username=normalized["username"],
        pinned_host_key_fingerprint=listing.pinned_host_key_fingerprint,
        authentication_kind=credential_binding.authentication_kind,
        reference_backend=credential_binding.reference_backend,
        reference_namespace=credential_binding.reference_namespace,
        reference_name=credential_binding.reference_name,
        reference_version=credential_binding.reference_version,
        remote_root_path=normalized["remote_root_path"],
        entry_relative_path=entry.relative_path,
        effective_remote_path=sftp_change._effective_remote_path(
            normalized["remote_root_path"],
            entry.relative_path,
        ),
    )
    display_name = entry.relative_path.replace("\\", "/").rsplit("/", 1)[-1]
    return RecurringProviderLineage(
        provider_kind="sftp",
        profile_hash=binding.profile_hash,
        stable_source_item_hash=binding.stable_source_item_hash,
        legacy_observation_id=None,
        legacy_checkpoint_id=None,
        sftp_observation_id=observation.id,
        sftp_checkpoint_id=checkpoint.id,
        observation_operation_kind=observation.observation_operation_kind,
        policy_hash=sftp_change._observation_policy_hash(),
        sftp_request=request,
        sftp_expected_auth_kind=credential_binding.authentication_kind,
        sftp_display_name_hash=hashlib.sha256(
            display_name.encode("utf-8")
        ).hexdigest(),
    )


def resolve_recurring_provider_lineage(
    db: Session,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
) -> RecurringProviderLineage:
    _ensure_binding_integrity(db, binding)
    if binding.provider_kind == "sftp":
        return _resolve_sftp(db, binding)
    return _resolve_legacy(db, binding)


def read_recurring_provider_metadata(
    lineage: RecurringProviderLineage,
    *,
    baseline_projection_hash: str,
) -> RecurringMetadataObservation:
    if lineage.provider_kind == "sftp":
        if (
            lineage.sftp_request is None
            or lineage.sftp_expected_auth_kind is None
            or lineage.sftp_display_name_hash is None
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP recurring metadata reader context is incomplete"
            )
        adapter = sftp_change._METADATA_ADAPTER
        if adapter is None:
            raise ExternalDocumentSourceConflictError(
                "SFTP exact-file metadata adapter is unavailable"
            )
        adapter_kind = getattr(adapter, "adapter_kind", None)
        if (
            not isinstance(adapter_kind, str)
            or not sftp_change._SAFE_ADAPTER_KIND.fullmatch(adapter_kind)
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP exact-file metadata adapter kind is invalid"
            )
        try:
            raw_result = adapter.stat_metadata(lineage.sftp_request)
        except Exception:
            raise ExternalDocumentSourceConflictError(
                "Due-tick SFTP exact-file metadata observation failed"
            ) from None
        observed = sftp_change._validate_adapter_result(
            raw_result,
            expected_auth_kind=lineage.sftp_expected_auth_kind,
        )
        if observed["result_status"] == "missing":
            return RecurringMetadataObservation(
                result_status="missing",
                observed_projection_hash=None,
                observed_display_name_hash=None,
                observed_version_token_hash=None,
                observed_byte_size=None,
                observed_modified_at=None,
                observed_mime_type_class=None,
                observation_adapter_kind=adapter_kind,
                policy_hash=lineage.policy_hash,
            )
        projection_hash = observed["observed_projection_hash"]
        return RecurringMetadataObservation(
            result_status=(
                "unchanged"
                if projection_hash == baseline_projection_hash
                else "changed"
            ),
            observed_projection_hash=projection_hash,
            observed_display_name_hash=lineage.sftp_display_name_hash,
            observed_version_token_hash=None,
            observed_byte_size=observed["observed_byte_size"],
            observed_modified_at=observed["observed_modified_at"],
            observed_mime_type_class=None,
            observation_adapter_kind=adapter_kind,
            policy_hash=lineage.policy_hash,
        )

    if (
        lineage.legacy_profile is None
        or lineage.legacy_locator is None
        or lineage.legacy_policy is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Legacy recurring metadata reader context is incomplete"
        )
    adapter = generic_change._OBSERVATION_ADAPTERS.get(
        (
            lineage.legacy_profile.provider_kind,
            lineage.legacy_policy.observation_operation_kind,
        )
    )
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "Exact-item metadata adapter is unavailable for due-tick observation"
        )
    adapter_kind = generic_change._normalize_identifier(
        adapter.adapter_kind,
        field="Due-tick observation adapter kind",
    )
    if (
        adapter.provider_kind != lineage.legacy_profile.provider_kind
        or adapter.client_kind != lineage.legacy_policy.client_kind
        or adapter.observation_operation_kind
        != lineage.legacy_policy.observation_operation_kind
        or adapter.provider_origin != lineage.legacy_policy.provider_origin
    ):
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation adapter policy drifted"
        )
    try:
        result = adapter.read_item_metadata(
            lineage.legacy_locator,
            lineage.legacy_policy,
        )
    except Exception:
        raise ExternalDocumentSourceConflictError(
            "Due-tick exact-item metadata observation failed"
        ) from None
    projection = generic_change._validate_result(result)
    if projection is None:
        return RecurringMetadataObservation(
            result_status="missing",
            observed_projection_hash=None,
            observed_display_name_hash=None,
            observed_version_token_hash=None,
            observed_byte_size=None,
            observed_modified_at=None,
            observed_mime_type_class=None,
            observation_adapter_kind=adapter_kind,
            policy_hash=lineage.policy_hash,
        )

    provider_item_id_hash = hashlib.sha256(
        projection.provider_item_id.encode("utf-8")
    ).hexdigest()
    if provider_item_id_hash != lineage.stable_source_item_hash:
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation returned a different provider item"
        )
    if projection.item_kind != "file":
        raise ExternalDocumentSourceConflictError(
            "Due-tick observation source is no longer a file"
        )
    facts = {
        "provider_item_id_hash": provider_item_id_hash,
        "item_kind": projection.item_kind,
        "display_name_hash": hashlib.sha256(
            projection.display_name.encode("utf-8")
        ).hexdigest(),
        "parent_item_id_hash": (
            hashlib.sha256(projection.parent_item_id.encode("utf-8")).hexdigest()
            if projection.parent_item_id is not None
            else None
        ),
        "mime_type_class": projection.mime_type_class,
        "byte_size": projection.byte_size,
        "modified_at": projection.modified_at,
        "version_token_hash": projection.version_token_hash,
    }
    projection_hash = generic_change._projection_hash(facts)
    return RecurringMetadataObservation(
        result_status=(
            "unchanged"
            if projection_hash == baseline_projection_hash
            else "changed"
        ),
        observed_projection_hash=projection_hash,
        observed_display_name_hash=facts["display_name_hash"],
        observed_version_token_hash=facts["version_token_hash"],
        observed_byte_size=facts["byte_size"],
        observed_modified_at=facts["modified_at"],
        observed_mime_type_class=facts["mime_type_class"],
        observation_adapter_kind=adapter_kind,
        policy_hash=lineage.policy_hash,
    )

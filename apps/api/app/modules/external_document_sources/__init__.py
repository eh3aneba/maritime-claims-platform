from app.modules.external_document_sources.change_detection_models import (
    ExternalDocumentSourceChangeDetectionExecution,
    ExternalDocumentSourceChangeDetectionReceipt,
)
from app.modules.external_document_sources.checkpoint_generation_models import (
    ExternalDocumentSourceCheckpointGenerationExecution,
    ExternalDocumentSourceCheckpointGenerationReceipt,
)
from app.modules.external_document_sources.checkpoint_generation_3_models import (
    ExternalDocumentSourceCheckpointGeneration3Execution,
    ExternalDocumentSourceCheckpointGeneration3Receipt,
)
from app.modules.external_document_sources.connection_authorization_models import (
    ExternalDocumentSourceConnectionAuthorization,
    ExternalDocumentSourceConnectionAuthorizationReceipt,
)
from app.modules.external_document_sources.connection_bootstrap_models import (
    ExternalDocumentSourceConnectionBootstrapExecution,
    ExternalDocumentSourceConnectionBootstrapExecutionReceipt,
)
from app.modules.external_document_sources.credential_reference_models import (
    ExternalDocumentSourceCredentialReferenceBinding,
    ExternalDocumentSourceCredentialReferenceReceipt,
)
from app.modules.external_document_sources.sftp_credential_reference_models import (
    ExternalDocumentSourceSftpCredentialReferenceBinding,
    ExternalDocumentSourceSftpCredentialReferenceReceipt,
)
from app.modules.external_document_sources.sftp_credential_health_models import (
    ExternalDocumentSourceSftpCredentialHealthQualification,
    ExternalDocumentSourceSftpCredentialHealthReceipt,
)
from app.modules.external_document_sources.sftp_handshake_authorization_models import (
    ExternalDocumentSourceSftpHandshakeAuthorization,
    ExternalDocumentSourceSftpHandshakeAuthorizationReceipt,
)
from app.modules.external_document_sources.sftp_handshake_execution_models import (
    ExternalDocumentSourceSftpHandshakeExecution,
    ExternalDocumentSourceSftpHandshakeExecutionReceipt,
)
from app.modules.external_document_sources.sftp_transport_verification_models import (
    ExternalDocumentSourceSftpTransportVerification,
    ExternalDocumentSourceSftpTransportVerificationReceipt,
)
from app.modules.external_document_sources.sftp_session_activation_models import (
    ExternalDocumentSourceSftpSessionActivation,
    ExternalDocumentSourceSftpSessionActivationReceipt,
)
from app.modules.external_document_sources.sftp_directory_listing_models import (
    ExternalDocumentSourceSftpDirectoryListing,
    ExternalDocumentSourceSftpDirectoryListingEntry,
    ExternalDocumentSourceSftpDirectoryListingReceipt,
)
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    ExternalDocumentSourceSftpFileContentProof,
    ExternalDocumentSourceSftpFileContentProofReceipt,
)
from app.modules.external_document_sources.sftp_quarantine_staging_models import (
    ExternalDocumentSourceSftpQuarantineStaging,
    ExternalDocumentSourceSftpQuarantineStagingReceipt,
)
from app.modules.external_document_sources.credential_reference_health_models import (
    ExternalDocumentSourceCredentialReferenceHealthQualification,
    ExternalDocumentSourceCredentialReferenceHealthReceipt,
)
from app.modules.external_document_sources.credential_resolution_execution_models import (
    ExternalDocumentSourceCredentialResolutionExecution,
    ExternalDocumentSourceCredentialResolutionExecutionReceipt,
)
from app.modules.external_document_sources.evidence_admission_authorization_models import (
    ExternalDocumentSourceEvidenceAdmissionAuthorization,
    ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt,
)
from app.modules.external_document_sources.evidence_admission_execution_models import (
    ExternalDocumentSourceEvidenceAdmissionExecution,
    ExternalDocumentSourceEvidenceAdmissionExecutionReceipt,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
    ExternalDocumentSourceDueTickObservationReceipt,
)
from app.modules.external_document_sources.observation_review_handoff_models import (
    ExternalDocumentSourceObservationReviewHandoff,
    ExternalDocumentSourceObservationReviewHandoffReceipt,
)
from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
    ExternalDocumentSourceObservationReviewDecision,
    ExternalDocumentSourceObservationReviewDecisionReceipt,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
    ExternalDocumentSourceObservationRefreshReceipt,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
    ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionExecution,
    ExternalDocumentSourceObservationRefreshAdmissionReceipt,
)
from app.modules.external_document_sources.due_tick_dispatch_models import (
    ExternalDocumentSourceDueTickDispatch,
    ExternalDocumentSourceDueTickDispatchReceipt,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_models import (
    ExternalDocumentSourceDueTickDispatchConsumption,
    ExternalDocumentSourceDueTickDispatchConsumptionReceipt,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
    ExternalDocumentSourceEvidenceFamilyBindingReceipt,
)
from app.modules.external_document_sources.family_version_admission_models import (
    ExternalDocumentSourceFamilyVersionAdmissionAuthorization,
    ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt,
    ExternalDocumentSourceFamilyVersionAdmissionExecution,
    ExternalDocumentSourceFamilyVersionAdmissionReceipt,
)
from app.modules.external_document_sources.processing_release_models import (
    ExternalDocumentSourceProcessingRelease,
    ExternalDocumentSourceProcessingReleaseReceipt,
)
from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
    ExternalDocumentSourceRecurringObservationScheduleReceipt,
)
from app.modules.external_document_sources.generation_3_change_detection_models import (
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
    ExternalDocumentSourceGeneration3ChangeDetectionReceipt,
)
from app.modules.external_document_sources.provider_client_activation_authorization_models import (
    ExternalDocumentSourceProviderClientActivationAuthorization,
    ExternalDocumentSourceProviderClientActivationAuthorizationReceipt,
)
from app.modules.external_document_sources.provider_client_activation_execution_models import (
    ExternalDocumentSourceProviderClientActivationExecution,
    ExternalDocumentSourceProviderClientActivationExecutionReceipt,
)
from app.modules.external_document_sources.provider_client_health_models import (
    ExternalDocumentSourceProviderClientHealthExecution,
    ExternalDocumentSourceProviderClientHealthReceipt,
)
from app.modules.external_document_sources.remote_content_staging_models import (
    ExternalDocumentSourceRemoteContentStagingExecution,
    ExternalDocumentSourceRemoteContentStagingReceipt,
)
from app.modules.external_document_sources.remote_file_content_read_models import (
    ExternalDocumentSourceRemoteFileContentReadExecution,
    ExternalDocumentSourceRemoteFileContentReadReceipt,
)
from app.modules.external_document_sources.remote_metadata_listing_models import (
    ExternalDocumentSourceRemoteMetadataListingExecution,
    ExternalDocumentSourceRemoteMetadataListingItem,
    ExternalDocumentSourceRemoteMetadataListingReceipt,
)
from app.modules.external_document_sources.successor_change_detection_models import (
    ExternalDocumentSourceSuccessorChangeDetectionExecution,
    ExternalDocumentSourceSuccessorChangeDetectionReceipt,
)
from app.modules.external_document_sources.successor_versioned_restaging_models import (
    ExternalDocumentSourceSuccessorVersionedRestagingExecution,
    ExternalDocumentSourceSuccessorVersionedRestagingReceipt,
)
from app.modules.external_document_sources.sync_checkpoint_models import (
    ExternalDocumentSourceSyncCheckpointExecution,
    ExternalDocumentSourceSyncCheckpointReceipt,
)
from app.modules.external_document_sources.token_acquisition_execution_models import (
    ExternalDocumentSourceTokenAcquisitionExecution,
    ExternalDocumentSourceTokenAcquisitionExecutionReceipt,
)
from app.modules.external_document_sources.versioned_restaging_models import (
    ExternalDocumentSourceVersionedRestagingExecution,
    ExternalDocumentSourceVersionedRestagingReceipt,
)

# Import downstream routers for route-registration side effects. They mount
# endpoints on the existing connection-authorization APIRouter, which is later
# included by external_document_sources.router.
from app.modules.external_document_sources import change_detection_router as _change_detection_router  # noqa: F401,E402
from app.modules.external_document_sources import checkpoint_generation_router as _checkpoint_generation_router  # noqa: F401,E402
from app.modules.external_document_sources import checkpoint_generation_3_router as _checkpoint_generation_3_router  # noqa: F401,E402
from app.modules.external_document_sources import connection_bootstrap_router as _connection_bootstrap_router  # noqa: F401,E402
from app.modules.external_document_sources import credential_reference_router as _credential_reference_router  # noqa: F401,E402
from app.modules.external_document_sources import sftp_credential_reference_router as _sftp_credential_reference_router  # noqa: F401,E402
from app.modules.external_document_sources import sftp_credential_health_router as _sftp_credential_health_router  # noqa: F401,E402
from app.modules.external_document_sources import sftp_handshake_authorization_router as _sftp_handshake_authorization_router  # noqa: F401,E402
from app.modules.external_document_sources import sftp_handshake_execution_router as _sftp_handshake_execution_router  # noqa: F401,E402
from app.modules.external_document_sources import sftp_transport_verification_router as _sftp_transport_verification_router  # noqa: F401,E402
from app.modules.external_document_sources import sftp_session_activation_router as _sftp_session_activation_router  # noqa: F401,E402
from app.modules.external_document_sources import sftp_directory_listing_router as _sftp_directory_listing_router  # noqa: F401,E402
from app.modules.external_document_sources import sftp_file_content_proof_router as _sftp_file_content_proof_router  # noqa: F401,E402
from app.modules.external_document_sources import sftp_quarantine_staging_router as _sftp_quarantine_staging_router  # noqa: F401,E402
from app.modules.external_document_sources import credential_reference_health_router as _credential_reference_health_router  # noqa: F401,E402
from app.modules.external_document_sources import credential_resolution_execution_router as _credential_resolution_execution_router  # noqa: F401,E402
from app.modules.external_document_sources import due_tick_observation_router as _due_tick_observation_router  # noqa: F401,E402
from app.modules.external_document_sources import evidence_admission_authorization_router as _evidence_admission_authorization_router  # noqa: F401,E402
from app.modules.external_document_sources import evidence_admission_execution_router as _evidence_admission_execution_router  # noqa: F401,E402
from app.modules.external_document_sources import evidence_family_binding_router as _evidence_family_binding_router  # noqa: F401,E402
from app.modules.external_document_sources import family_version_admission_router as _family_version_admission_router  # noqa: F401,E402
from app.modules.external_document_sources import generation_3_change_detection_router as _generation_3_change_detection_router  # noqa: F401,E402
from app.modules.external_document_sources import provider_client_activation_authorization_router as _provider_client_activation_authorization_router  # noqa: F401,E402
from app.modules.external_document_sources import provider_client_activation_execution_router as _provider_client_activation_execution_router  # noqa: F401,E402
from app.modules.external_document_sources import provider_client_health_router as _provider_client_health_router  # noqa: F401,E402
from app.modules.external_document_sources import remote_content_staging_router as _remote_content_staging_router  # noqa: F401,E402
from app.modules.external_document_sources import remote_file_content_read_router as _remote_file_content_read_router  # noqa: F401,E402
from app.modules.external_document_sources import remote_metadata_listing_router as _remote_metadata_listing_router  # noqa: F401,E402
from app.modules.external_document_sources import recurring_observation_schedule_router as _recurring_observation_schedule_router  # noqa: F401,E402
from app.modules.external_document_sources import observation_review_decision_router as _observation_review_decision_router  # noqa: F401,E402
from app.modules.external_document_sources import observation_refresh_execution_router as _observation_refresh_execution_router  # noqa: F401,E402
from app.modules.external_document_sources import observation_refresh_admission_authorization_router as _observation_refresh_admission_authorization_router  # noqa: F401,E402
from app.modules.external_document_sources import observation_refresh_admission_execution_router as _observation_refresh_admission_execution_router  # noqa: F401,E402
from app.modules.external_document_sources import successor_change_detection_router as _successor_change_detection_router  # noqa: F401,E402
from app.modules.external_document_sources import successor_versioned_restaging_router as _successor_versioned_restaging_router  # noqa: F401,E402
from app.modules.external_document_sources import sync_checkpoint_router as _sync_checkpoint_router  # noqa: F401,E402
from app.modules.external_document_sources import token_acquisition_execution_router as _token_acquisition_execution_router  # noqa: F401,E402
from app.modules.external_document_sources import versioned_restaging_router as _versioned_restaging_router  # noqa: F401,E402

__all__ = [
    "ExternalDocumentSourceChangeDetectionExecution",
    "ExternalDocumentSourceChangeDetectionReceipt",
    "ExternalDocumentSourceCheckpointGenerationExecution",
    "ExternalDocumentSourceCheckpointGenerationReceipt",
    "ExternalDocumentSourceCheckpointGeneration3Execution",
    "ExternalDocumentSourceCheckpointGeneration3Receipt",
    "ExternalDocumentSourceConnectionAuthorization",
    "ExternalDocumentSourceConnectionAuthorizationReceipt",
    "ExternalDocumentSourceConnectionBootstrapExecution",
    "ExternalDocumentSourceConnectionBootstrapExecutionReceipt",
    "ExternalDocumentSourceCredentialReferenceBinding",
    "ExternalDocumentSourceCredentialReferenceReceipt",
    "ExternalDocumentSourceSftpCredentialReferenceBinding",
    "ExternalDocumentSourceSftpCredentialReferenceReceipt",
    "ExternalDocumentSourceSftpCredentialHealthQualification",
    "ExternalDocumentSourceSftpCredentialHealthReceipt",
    "ExternalDocumentSourceSftpHandshakeAuthorization",
    "ExternalDocumentSourceSftpHandshakeAuthorizationReceipt",
    "ExternalDocumentSourceSftpHandshakeExecution",
    "ExternalDocumentSourceSftpHandshakeExecutionReceipt",
    "ExternalDocumentSourceSftpTransportVerification",
    "ExternalDocumentSourceSftpTransportVerificationReceipt",
    "ExternalDocumentSourceSftpSessionActivation",
    "ExternalDocumentSourceSftpSessionActivationReceipt",
    "ExternalDocumentSourceCredentialReferenceHealthQualification",
    "ExternalDocumentSourceCredentialReferenceHealthReceipt",
    "ExternalDocumentSourceCredentialResolutionExecution",
    "ExternalDocumentSourceCredentialResolutionExecutionReceipt",
    "ExternalDocumentSourceEvidenceAdmissionAuthorization",
    "ExternalDocumentSourceEvidenceAdmissionAuthorizationReceipt",
    "ExternalDocumentSourceEvidenceAdmissionExecution",
    "ExternalDocumentSourceEvidenceAdmissionExecutionReceipt",
    "ExternalDocumentSourceDueTickObservationExecution",
    "ExternalDocumentSourceDueTickObservationReceipt",
    "ExternalDocumentSourceObservationReviewHandoff",
    "ExternalDocumentSourceObservationReviewHandoffReceipt",
    "ExternalDocumentSourceObservationReviewDecision",
    "ExternalDocumentSourceObservationReviewDecisionReceipt",
    "ExternalDocumentSourceObservationRefreshAuthorization",
    "ExternalDocumentSourceObservationRefreshExecution",
    "ExternalDocumentSourceObservationRefreshReceipt",
    "ExternalDocumentSourceObservationRefreshAdmissionAuthorization",
    "ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt",
    "ExternalDocumentSourceObservationRefreshAdmissionExecution",
    "ExternalDocumentSourceObservationRefreshAdmissionReceipt",
    "ExternalDocumentSourceDueTickDispatch",
    "ExternalDocumentSourceDueTickDispatchReceipt",
    "ExternalDocumentSourceDueTickDispatchConsumption",
    "ExternalDocumentSourceDueTickDispatchConsumptionReceipt",
    "ExternalDocumentSourceEvidenceFamilyBinding",
    "ExternalDocumentSourceEvidenceFamilyBindingReceipt",
    "ExternalDocumentSourceFamilyVersionAdmissionAuthorization",
    "ExternalDocumentSourceFamilyVersionAdmissionAuthorizationReceipt",
    "ExternalDocumentSourceFamilyVersionAdmissionExecution",
    "ExternalDocumentSourceFamilyVersionAdmissionReceipt",
    "ExternalDocumentSourceProcessingRelease",
    "ExternalDocumentSourceProcessingReleaseReceipt",
    "ExternalDocumentSourceRecurringObservationSchedule",
    "ExternalDocumentSourceRecurringObservationScheduleReceipt",
    "ExternalDocumentSourceGeneration3ChangeDetectionExecution",
    "ExternalDocumentSourceGeneration3ChangeDetectionReceipt",
    "ExternalDocumentSourceProviderClientActivationAuthorization",
    "ExternalDocumentSourceProviderClientActivationAuthorizationReceipt",
    "ExternalDocumentSourceProviderClientActivationExecution",
    "ExternalDocumentSourceProviderClientActivationExecutionReceipt",
    "ExternalDocumentSourceProviderClientHealthExecution",
    "ExternalDocumentSourceProviderClientHealthReceipt",
    "ExternalDocumentSourceRemoteContentStagingExecution",
    "ExternalDocumentSourceRemoteContentStagingReceipt",
    "ExternalDocumentSourceRemoteFileContentReadExecution",
    "ExternalDocumentSourceRemoteFileContentReadReceipt",
    "ExternalDocumentSourceRemoteMetadataListingExecution",
    "ExternalDocumentSourceRemoteMetadataListingItem",
    "ExternalDocumentSourceRemoteMetadataListingReceipt",
    "ExternalDocumentSourceSuccessorChangeDetectionExecution",
    "ExternalDocumentSourceSuccessorChangeDetectionReceipt",
    "ExternalDocumentSourceSuccessorVersionedRestagingExecution",
    "ExternalDocumentSourceSuccessorVersionedRestagingReceipt",
    "ExternalDocumentSourceSyncCheckpointExecution",
    "ExternalDocumentSourceSyncCheckpointReceipt",
    "ExternalDocumentSourceTokenAcquisitionExecution",
    "ExternalDocumentSourceTokenAcquisitionExecutionReceipt",
    "ExternalDocumentSourceVersionedRestagingExecution",
    "ExternalDocumentSourceVersionedRestagingReceipt",
]
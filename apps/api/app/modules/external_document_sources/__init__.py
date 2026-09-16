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
from app.modules.external_document_sources.credential_reference_health_models import (
    ExternalDocumentSourceCredentialReferenceHealthQualification,
    ExternalDocumentSourceCredentialReferenceHealthReceipt,
)
from app.modules.external_document_sources.credential_resolution_execution_models import (
    ExternalDocumentSourceCredentialResolutionExecution,
    ExternalDocumentSourceCredentialResolutionExecutionReceipt,
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
from app.modules.external_document_sources.remote_file_content_read_models import (
    ExternalDocumentSourceRemoteFileContentReadExecution,
    ExternalDocumentSourceRemoteFileContentReadReceipt,
)
from app.modules.external_document_sources.remote_metadata_listing_models import (
    ExternalDocumentSourceRemoteMetadataListingExecution,
    ExternalDocumentSourceRemoteMetadataListingItem,
    ExternalDocumentSourceRemoteMetadataListingReceipt,
)
from app.modules.external_document_sources.token_acquisition_execution_models import (
    ExternalDocumentSourceTokenAcquisitionExecution,
    ExternalDocumentSourceTokenAcquisitionExecutionReceipt,
)

# Import downstream routers for route-registration side effects. They mount
# endpoints on the existing connection-authorization APIRouter, which is later
# included by external_document_sources.router.
from app.modules.external_document_sources import connection_bootstrap_router as _connection_bootstrap_router  # noqa: F401,E402
from app.modules.external_document_sources import credential_reference_router as _credential_reference_router  # noqa: F401,E402
from app.modules.external_document_sources import credential_reference_health_router as _credential_reference_health_router  # noqa: F401,E402
from app.modules.external_document_sources import credential_resolution_execution_router as _credential_resolution_execution_router  # noqa: F401,E402
from app.modules.external_document_sources import provider_client_activation_authorization_router as _provider_client_activation_authorization_router  # noqa: F401,E402
from app.modules.external_document_sources import provider_client_activation_execution_router as _provider_client_activation_execution_router  # noqa: F401,E402
from app.modules.external_document_sources import provider_client_health_router as _provider_client_health_router  # noqa: F401,E402
from app.modules.external_document_sources import remote_file_content_read_router as _remote_file_content_read_router  # noqa: F401,E402
from app.modules.external_document_sources import remote_metadata_listing_router as _remote_metadata_listing_router  # noqa: F401,E402
from app.modules.external_document_sources import token_acquisition_execution_router as _token_acquisition_execution_router  # noqa: F401,E402

__all__ = [
    "ExternalDocumentSourceConnectionAuthorization",
    "ExternalDocumentSourceConnectionAuthorizationReceipt",
    "ExternalDocumentSourceConnectionBootstrapExecution",
    "ExternalDocumentSourceConnectionBootstrapExecutionReceipt",
    "ExternalDocumentSourceCredentialReferenceBinding",
    "ExternalDocumentSourceCredentialReferenceReceipt",
    "ExternalDocumentSourceCredentialReferenceHealthQualification",
    "ExternalDocumentSourceCredentialReferenceHealthReceipt",
    "ExternalDocumentSourceCredentialResolutionExecution",
    "ExternalDocumentSourceCredentialResolutionExecutionReceipt",
    "ExternalDocumentSourceProviderClientActivationAuthorization",
    "ExternalDocumentSourceProviderClientActivationAuthorizationReceipt",
    "ExternalDocumentSourceProviderClientActivationExecution",
    "ExternalDocumentSourceProviderClientActivationExecutionReceipt",
    "ExternalDocumentSourceProviderClientHealthExecution",
    "ExternalDocumentSourceProviderClientHealthReceipt",
    "ExternalDocumentSourceRemoteFileContentReadExecution",
    "ExternalDocumentSourceRemoteFileContentReadReceipt",
    "ExternalDocumentSourceRemoteMetadataListingExecution",
    "ExternalDocumentSourceRemoteMetadataListingItem",
    "ExternalDocumentSourceRemoteMetadataListingReceipt",
    "ExternalDocumentSourceTokenAcquisitionExecution",
    "ExternalDocumentSourceTokenAcquisitionExecutionReceipt",
]
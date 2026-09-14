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
from app.modules.external_document_sources.provider_client_activation_authorization_models import (
    ExternalDocumentSourceProviderClientActivationAuthorization,
    ExternalDocumentSourceProviderClientActivationAuthorizationReceipt,
)
from app.modules.external_document_sources.provider_client_activation_execution_models import (
    ExternalDocumentSourceProviderClientActivationExecution,
    ExternalDocumentSourceProviderClientActivationExecutionReceipt,
)

# Import downstream routers for route-registration side effects. They mount
# endpoints on the existing connection-authorization APIRouter, which is later
# included by external_document_sources.router.
from app.modules.external_document_sources import connection_bootstrap_router as _connection_bootstrap_router  # noqa: F401,E402
from app.modules.external_document_sources import credential_reference_router as _credential_reference_router  # noqa: F401,E402
from app.modules.external_document_sources import credential_reference_health_router as _credential_reference_health_router  # noqa: F401,E402
from app.modules.external_document_sources import provider_client_activation_authorization_router as _provider_client_activation_authorization_router  # noqa: F401,E402
from app.modules.external_document_sources import provider_client_activation_execution_router as _provider_client_activation_execution_router  # noqa: F401,E402

__all__ = [
    "ExternalDocumentSourceConnectionAuthorization",
    "ExternalDocumentSourceConnectionAuthorizationReceipt",
    "ExternalDocumentSourceConnectionBootstrapExecution",
    "ExternalDocumentSourceConnectionBootstrapExecutionReceipt",
    "ExternalDocumentSourceCredentialReferenceBinding",
    "ExternalDocumentSourceCredentialReferenceReceipt",
    "ExternalDocumentSourceCredentialReferenceHealthQualification",
    "ExternalDocumentSourceCredentialReferenceHealthReceipt",
    "ExternalDocumentSourceProviderClientActivationAuthorization",
    "ExternalDocumentSourceProviderClientActivationAuthorizationReceipt",
    "ExternalDocumentSourceProviderClientActivationExecution",
    "ExternalDocumentSourceProviderClientActivationExecutionReceipt",
]

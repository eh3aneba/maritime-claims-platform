from app.modules.external_document_sources.connection_authorization_models import (
    ExternalDocumentSourceConnectionAuthorization,
    ExternalDocumentSourceConnectionAuthorizationReceipt,
)
from app.modules.external_document_sources.connection_bootstrap_models import (
    ExternalDocumentSourceConnectionBootstrapExecution,
    ExternalDocumentSourceConnectionBootstrapExecutionReceipt,
)

# Import the Phase 17.5-D router for route-registration side effects. It mounts
# its endpoints on the existing connection-authorization APIRouter, which is
# later included by external_document_sources.router.
from app.modules.external_document_sources import connection_bootstrap_router as _connection_bootstrap_router  # noqa: F401,E402

__all__ = [
    "ExternalDocumentSourceConnectionAuthorization",
    "ExternalDocumentSourceConnectionAuthorizationReceipt",
    "ExternalDocumentSourceConnectionBootstrapExecution",
    "ExternalDocumentSourceConnectionBootstrapExecutionReceipt",
]

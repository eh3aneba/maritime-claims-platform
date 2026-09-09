# Import retention governance models whenever the claims package is loaded so
# SQLAlchemy/Alembic metadata sees the preservation tables alongside Claim.
from app.modules.claims.retention_disposal_dry_run_models import DisposalDryRunCeremony  # noqa: F401
from app.modules.claims.retention_disposal_manifest_models import DisposalExecutionManifest  # noqa: F401
from app.modules.claims.retention_disposal_models import DisposalAuthorization  # noqa: F401
from app.modules.claims.retention_disposal_quarantine_models import DisposalQuarantineStage  # noqa: F401
from app.modules.claims.retention_models import (  # noqa: F401
    ClaimLegalHold,
    LegalHoldProposal,
    TenantRetentionPolicy,
)
from app.modules.claims.retention_signal_models import PreservationSignalProfile  # noqa: F401

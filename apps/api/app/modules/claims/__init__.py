# Import retention governance models whenever the claims package is loaded so
# SQLAlchemy/Alembic metadata sees the preservation tables alongside Claim.
from app.modules.claims.retention_models import ClaimLegalHold, TenantRetentionPolicy  # noqa: F401

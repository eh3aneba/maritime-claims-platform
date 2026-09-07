"""Authentication and authorization module."""

# Register protocol-specific SQLAlchemy models whenever the auth package is loaded so
# application/Alembic metadata remains complete without widening auth.models itself.
from app.modules.auth.saml_models import (  # noqa: F401
    SamlAuthnTransaction,
    SamlTrustRuntimeProfile,
)

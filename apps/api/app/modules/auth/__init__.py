"""Authentication and authorization module."""

# Register protocol/policy-specific SQLAlchemy models whenever the auth package is loaded so
# application/Alembic metadata remains complete without widening auth.models itself.
from app.modules.auth.mfa_policy_models import MfaPolicy  # noqa: F401
from app.modules.auth.mfa_recovery_models import MfaRecoveryCode  # noqa: F401
from app.modules.auth.mfa_reset_models import MfaFactorResetRequest  # noqa: F401
from app.modules.auth.saml_models import (  # noqa: F401
    SamlAuthnTransaction,
    SamlTrustRuntimeProfile,
)
from app.modules.auth.webauthn_models import (  # noqa: F401
    WebAuthnAuthenticationTransaction,
    WebAuthnCredential,
    WebAuthnRegistrationTransaction,
    WebAuthnRelyingPartyProfile,
)

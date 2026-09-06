from __future__ import annotations

import os
import re
from dataclasses import dataclass

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_BACKENDS = {"env", "vault", "secret-manager"}


class CredentialReferenceError(ValueError):
    def __init__(self, code: str = "credential_reference_invalid"):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProviderCredentialMetadata:
    backend: str
    reference_configured: bool
    resolver_available: bool


def inspect_credential_reference(reference: str) -> ProviderCredentialMetadata:
    """Validate a credential locator without returning or logging its locator component."""
    if not isinstance(reference, str) or len(reference) > 240 or "://" not in reference:
        raise CredentialReferenceError()
    backend, locator = reference.split("://", 1)
    if backend not in _BACKENDS or not locator or locator != locator.strip():
        raise CredentialReferenceError()
    if any(ord(char) < 33 or ord(char) == 127 for char in locator):
        raise CredentialReferenceError()
    if backend == "env" and not _ENV_NAME.fullmatch(locator):
        raise CredentialReferenceError()
    return ProviderCredentialMetadata(
        backend=backend,
        reference_configured=True,
        resolver_available=backend == "env",
    )


def resolve_credential_reference(reference: str) -> str:
    """Resolve a validated provider credential reference without persisting its value."""
    metadata = inspect_credential_reference(reference)
    _, locator = reference.split("://", 1)
    if metadata.backend != "env":
        raise CredentialReferenceError("credential_resolver_unavailable")
    value = os.getenv(locator)
    if not value:
        raise CredentialReferenceError("credential_reference_unresolved")
    return value

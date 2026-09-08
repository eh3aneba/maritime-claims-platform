# ADR-151: Governed SAML AuthnContext external MFA assurance equivalence

## Status
Accepted for Phase 17.1-R implementation and validation.

## Context
MCRI already validates SAML responses against an immutable tenant/provider trust-runtime profile, verifies the signed Assertion, enforces issuer/audience/destination/request correlation and creates an AuthSession only for an explicitly bound, active application User. Phase 17.1-Q added a separately governed OIDC MFA-assurance equivalence layer, but SAML login still treated AuthnContext only as non-authoritative identity-protocol content.

Enterprise SAML identity providers can emit `AuthnContextClassRef` values describing the authentication ceremony used upstream. Treating those values as MFA automatically would give provider-specific semantics unbounded authority, make in-flight configuration rotation ambiguous and weaken the separation between identity proof and application authorization.

## Decision
SAML external MFA equivalence is disabled unless an ADMIN explicitly creates an enabled, immutable assurance profile for one tenant/provider and the exact current SAML trust/runtime profile.

Each assurance profile:
- is immutable and versioned;
- is bound to exact Organization, SAML provider and trust/runtime-profile id/number/hash;
- contains a bounded exact allowlist of accepted `AuthnContextClassRef` strings;
- requires at least one accepted value when enabled;
- is hashed with its complete public policy lineage;
- is managed only through MFA-sensitive tenant-scoped Admin endpoints.

At SAML authentication start, MCRI creates a one-to-one assurance binding for the exact `SamlAuthnTransaction`. The binding pins either the current assurance profile compatible with that transaction's exact trust/runtime profile or explicit absence of a profile. Later profile rotation cannot change the authority source of an in-flight transaction.

AuthnContext is evaluated only after the same SAMLResponse has successfully completed ordinary SAML verification for that exact callback and transaction. Assurance extraction is deliberately narrower than identity parsing: exactly one signed Assertion, exactly one `AuthnStatement`, exactly one `AuthnContext`, and exactly one bounded `AuthnContextClassRef` are eligible. Missing, malformed, ambiguous or non-matching AuthnContext does not fail an otherwise valid SAML identity login; it only fails to elevate MFA assurance.

When the pinned policy matches:
- only the exact callback-created AuthSession receives `mfa_verified_at` and `mfa_method=saml_external`;
- `mfa_factor_id` remains null because no application-controlled factor is being asserted;
- the transaction assurance binding records the trust/profile lineage, verification timestamp, evidence type `authn_context`, and a domain-separated SHA-256 digest of the matched class reference;
- raw SAMLResponse, RelayState, request id, external subject and raw AuthnContext values are not persisted or audited as assurance evidence.

Tenant MFA enforcement accepts `saml_external` only when the exact AuthSession, consumed SAML transaction, provider, pinned trust/runtime profile, pinned assurance profile and recorded verification provenance remain internally consistent. Database User/Organization membership and `User.role` remain authoritative; SAML role/group attributes never become application authorization.

## Consequences
- A tenant can explicitly recognize its own SAML IdP MFA ceremony without creating a generic external-MFA bypass.
- Mid-flight policy rotation is deterministic because the transaction carries a one-to-one pinned assurance binding.
- Existing SAML login remains backward compatible when no assurance profile exists or evidence does not match.
- Existing TOTP, recovery-code, WebAuthn and OIDC assurance paths remain independent.
- An externally assured SAML session can satisfy mandatory tenant MFA only for that exact verified session and provenance chain.
- Historical assurance profiles remain immutable; operational termination of issued sessions continues to use explicit session revocation rather than retroactive policy rewriting.

## Explicit deferrals
- IdP-driven User creation, tenant selection, role/group mapping and external binding creation remain prohibited.
- SCIM/provisioning is a separate enterprise-identity tranche.
- Passwordless primary-login changes are not introduced.
- Generic SAML attributes, unsigned metadata and response-level untrusted content are not MFA evidence.
- No claims, coverage, causation, liability, reserve, settlement, payment or fraud authority is affected.
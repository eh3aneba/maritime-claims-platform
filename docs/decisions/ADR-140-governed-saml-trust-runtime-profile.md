# ADR-140: Governed SAML trust and runtime profile foundation

- **Status:** Accepted
- **Date:** 2026-09-07
- **Decision owners:** MCRI product and engineering
- **Related:** Issue #259, Enterprise Identity 17.1-G; ADR-135; ADR-139

## Context

ADR-135 created the provider-neutral tenant-scoped identity registry and explicit external account binding.
ADR-139 completed a bounded live OIDC path while preserving application-database authority over tenant
membership, User lifecycle and `User.role`. Roadmap issue #25 identifies SAML as the next incomplete
Enterprise Identity capability.

A live SAML endpoint combines several security boundaries: provider trust configuration, SP runtime
configuration, certificate validation, request correlation, XML signature verification, assertion lifetime
and audience checks, subject-to-account resolution, and session issuance. Implementing all of those in one
change would make the authority transition difficult to review and would increase XML/signature risk.

## Decision

MCRI will first add an immutable, tenant-scoped `SamlTrustRuntimeProfile` for an existing enabled
`EnterpriseIdentityProvider` whose protocol is `saml`.

Each profile pins only bounded public verification/runtime configuration:

- the provider ID and server-derived IdP entity identifier;
- an exact HTTPS IdP SSO endpoint;
- an exact SP entity ID;
- an exact HTTPS Assertion Consumer Service URL;
- `HTTP-Redirect` as the only accepted future AuthnRequest binding for this foundation;
- `HTTP-POST` as the only accepted future response binding;
- RSA-SHA256 as the only supported signing algorithm;
- SHA-256 as the only supported digest algorithm;
- one normalized public X.509 IdP signing certificate and its SHA-256 fingerprint;
- immutable profile number/hash and previous-profile-hash lineage; and
- the creating application Admin.

The certificate is public verification material, not secret custody. It must parse as exactly one PEM X.509
certificate, be currently valid, and expose an RSA public key of at least 2048 bits. Private keys, provider
passwords and decryption credentials are never accepted by this profile.

Only a same-tenant application Admin may create or read profiles. Exact canonical replay is idempotent.
Changed public configuration creates a new append-only profile and preserves the previous hash.

## Authorization boundary

This profile does not authenticate anyone and does not widen application authority.

- No SAML metadata is fetched or auto-discovered.
- No AuthnRequest is constructed or transmitted.
- No SAML Response or Assertion is accepted, parsed or verified.
- No external-authenticated `AuthSession` is issued.
- No User or `ExternalIdentityBinding` is created automatically.
- No email fallback exists.
- No tenant is selected from SAML attributes.
- No SAML group or attribute modifies `User.role` or claims authority.
- No raw SAML assertion is persisted or audited.
- Local-password and existing OIDC authentication remain unchanged.

The application database remains authoritative for tenant membership, User/Organization lifecycle and
permissions.

## Security consequences

### Positive

- SAML trust and runtime inputs become tenant-scoped and immutable before XML authentication exists;
- future assertion verification can be pinned to an exact profile instead of mutable metadata;
- certificate/public-key requirements fail closed before any live authentication flow;
- public verification material is separated from future secret/private-key custody;
- no SAML claim can create or elevate application authority in this tranche.

### Costs

- SAML login is intentionally still unavailable;
- certificate rotation requires a new profile version;
- deployments must explicitly configure public SAML endpoints and certificates rather than relying on
  metadata discovery.

## Deferred

A later separately authorized tranche may add short-lived SAML request correlation, AuthnRequest creation,
XML parsing/signature verification, issuer/audience/destination/InResponseTo/time-condition validation,
existing-binding-only subject resolution and bound session issuance.

Still separately deferred are metadata discovery, Single Logout, SP signing/decryption private-key custody,
SCIM/automatic provisioning, email linking, group-to-role mapping, tenant selection from IdP attributes,
MFA and local-password removal. Each requires its own scope, tests, ADR and merge authorization.

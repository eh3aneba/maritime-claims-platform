# ADR-136: Governed OIDC trust profile version pinning

- **Status:** Accepted
- **Date:** 2026-09-07
- **Decision owners:** MCRI product and engineering
- **Related:** Issue #251, Enterprise Identity 17.1-C; ADR-134; ADR-135

## Context

ADR-134 established server-side authentication sessions. ADR-135 added tenant-scoped external identity
provider registration and explicit bindings between external subjects and existing application Users.
Neither decision allows MCRI to accept a signed external authentication result yet.

A future OIDC callback must not trust mutable discovery output, arbitrary token algorithms, a client-supplied
issuer, or an unpinned audience. Before network retrieval and signature verification are introduced, MCRI
needs an application-owned record of the exact public verification policy that an Admin has approved for a
tenant's OIDC provider.

Combining trust-policy configuration with redirect handling, token exchange, JWKS network retrieval and
session issuance would make the authentication authority boundary too large for one tranche.

## Decision

MCRI will introduce append-only `OidcTrustProfile` records for governed OIDC providers.

Each profile stores only public verification policy:

- tenant organization ID;
- governed provider ID;
- monotonically increasing profile number;
- issuer identifier copied from the existing provider registry;
- audience/client ID;
- JWKS URI;
- a bounded list of allowed asymmetric signing algorithms;
- deterministic profile hash;
- previous profile hash; and
- creating application Admin identity and timestamp.

The issuer is never accepted from the trust-profile write payload. It is copied server-side from the
existing `EnterpriseIdentityProvider`. The write schema rejects extra fields so a caller cannot inject a
second issuer or another undeclared authority field.

The initial signing-algorithm allowlist is intentionally small: `RS256` and `ES256`. `none`, HMAC algorithms
and all unlisted algorithms fail closed. Expansion requires a later reviewed change.

JWKS URIs must use HTTPS. Plain HTTP is permitted only for explicit local/test environments and loopback
hosts. Credentials and URI fragments are rejected.

## Lineage and idempotency

Trust profiles are immutable application records.

A canonical hash is computed from tenant ID, provider ID, server-derived issuer, audience, JWKS URI and the
normalized signing-algorithm list. Replaying the exact same canonical profile returns the existing record.
Changing any canonical trust input creates the next profile version and preserves the previous profile hash.

No previous record is modified or deleted by profile rotation.

## Authorization boundary

Creating a trust profile does not authenticate anyone and grants no application authority.

- Only a same-tenant application Admin may create or read profiles.
- The provider must already exist, be enabled and use protocol `oidc`.
- No network discovery or JWKS retrieval occurs.
- No redirect or callback endpoint is added.
- No authorization code or token is exchanged.
- No JWT or external assertion is accepted or verified.
- No client secret, private key, certificate, access token, ID token or raw assertion is stored.
- No external-authenticated `AuthSession` is issued.
- No User is created and no tenant is selected from external claims.
- No group or claim may modify `User.role`.
- Application User/Organization state and DB `User.role` remain authoritative.

## Security consequences

### Positive

- a later verifier has an immutable, auditable source for issuer/audience/JWKS/algorithm policy;
- discovery metadata cannot silently widen trust;
- algorithm downgrade to `none` or HMAC fails before any live SSO flow exists;
- provider trust changes create explicit lineage instead of mutating history;
- no external authentication authority is introduced in this phase.

### Costs

- OIDC login remains unavailable until a later signed authentication-flow tranche;
- Admins must explicitly maintain public trust-profile versions;
- the initial algorithm allowlist may need controlled expansion for some enterprise IdPs.

## Deferred

This ADR does not implement:

- OIDC redirect/state/nonce/PKCE transactions;
- discovery or JWKS network retrieval/caching;
- JWT signature, issuer, audience, nonce or time-claim verification;
- authorization-code or token exchange;
- client secret/private-key custody;
- external-authenticated session issuance;
- SAML;
- MFA;
- SCIM or automatic user provisioning;
- IdP group-to-role mapping.

Each requires separate review, testing and merge authorization.

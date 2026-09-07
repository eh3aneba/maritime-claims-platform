# ADR-137: OIDC authorization transaction custody

- **Status:** Accepted
- **Date:** 2026-09-07
- **Decision owners:** MCRI product and engineering
- **Related:** Issue #253, Enterprise Identity 17.1-D; ADR-134; ADR-135; ADR-136

## Context

ADR-134 established server-side authentication sessions. ADR-135 introduced tenant-scoped external identity providers and explicit bindings to existing application Users. ADR-136 added immutable OIDC trust profiles containing the public verification policy that a later signed authentication flow must use.

MCRI still must not accept an OIDC callback until the application can bind a browser authorization attempt to the exact tenant, provider and trust-profile version that initiated it. State, nonce and PKCE values are security-sensitive because they protect correlation, replay and authorization-code interception. Persisting their raw values would unnecessarily expand credential-like material at rest.

Combining authorization-transaction custody with live redirects, discovery, JWKS retrieval, token exchange, JWT verification and external session issuance would make the identity boundary too large for one reviewed tranche.

## Decision

MCRI will add short-lived `OidcAuthorizationTransaction` records. A transaction is created only from an explicit application organization slug and provider key. Tenant selection never comes from an IdP callback or external claim.

The provider must already:

- belong to the selected active Organization;
- be enabled;
- use protocol `oidc`; and
- have a current immutable `OidcTrustProfile`.

The transaction snapshots and permanently binds to:

- organization ID;
- provider ID;
- exact trust-profile ID;
- trust-profile number; and
- trust-profile hash.

A later trust-profile rotation does not rewrite an existing transaction. A future callback verifier must use the transaction's pinned source rather than silently adopting the newest trust profile.

## Ephemeral cryptographic material

At transaction creation MCRI generates:

- state from at least 256 bits of cryptographic randomness;
- nonce from at least 256 bits of cryptographic randomness; and
- a high-entropy PKCE code verifier.

Only `S256` PKCE is supported. The code challenge is `BASE64URL(SHA256(code_verifier))` without padding.

Raw state, raw nonce and raw code verifier are returned once to the initiating caller and are never stored in the database or written to the audit log. The database stores only:

- SHA-256 state fingerprint;
- SHA-256 nonce fingerprint; and
- S256 PKCE code challenge.

Transactions expire after 10 minutes. They also carry nullable consumed and cancelled timestamps for one-time lifecycle enforcement.

## One-time internal lifecycle primitive

This tranche includes internal consume and cancel primitives so the next callback-verification tranche can reuse reviewed custody semantics rather than redefining them.

Consume requires the exact transaction ID plus raw state, nonce and PKCE verifier. Validation uses constant-time comparison against persisted derived values. Consumption fails closed when the transaction is expired, cancelled, already consumed, the provider is disabled/unavailable, or the referenced trust-profile record no longer matches the immutable transaction snapshot.

Cancellation requires the exact transaction ID plus possession of raw state. Consume and cancel write bounded audit events without raw cryptographic material.

These primitives are not callback endpoints and do not themselves authenticate an external identity.

## Public API boundary

The only new public endpoint is transaction creation:

`POST /auth/oidc/transactions`

It accepts explicit application-owned `organization_slug` and `provider_key`. It returns the one-time state/nonce/PKCE material plus bounded public provider and pinned trust-profile metadata required by a later authorization redirect builder.

The endpoint does not redirect a browser and does not contact the IdP.

## Authorization boundary

An OIDC authorization transaction grants no application authority.

- No redirect or callback is processed.
- No discovery document or JWKS is fetched.
- No authorization code is accepted or exchanged.
- No ID/access/refresh token is accepted, verified or stored.
- No JWT/JWS signature, issuer, audience, nonce or time claim is verified.
- No client secret, private key or certificate is stored.
- No `ExternalIdentityBinding` is created or changed.
- No User is provisioned.
- No tenant is selected from external claims.
- No IdP group or claim changes `User.role`.
- No external-authenticated `AuthSession` is issued.
- Local password login is unchanged.

Application User/Organization state and DB `User.role` remain authoritative.

## Security consequences

### Positive

- state, nonce and PKCE are cryptographically strong and short-lived;
- raw anti-replay/PKCE values are minimized at rest;
- every future callback can be tied to one exact provider and trust-profile version;
- trust-profile rotation cannot silently change verification policy for an in-flight transaction;
- one-time consume semantics are reviewed before live callback handling exists;
- audit records preserve lifecycle without recording raw cryptographic proof.

### Costs

- live OIDC login still does not exist after this tranche;
- callers must temporarily retain the returned state, nonce and PKCE verifier;
- the public transaction-start endpoint will require normal edge abuse/rate controls before broad internet exposure;
- a later tranche still needs authorization endpoint configuration, token exchange, JWKS retrieval/caching, signature verification and external session issuance.

## Deferred

This ADR does not implement:

- IdP authorization redirect construction or execution;
- OIDC discovery;
- JWKS retrieval or caching;
- authorization-code or token endpoint interaction;
- JWT/JWS signature verification;
- issuer, audience, nonce or token-time validation;
- client-secret/private-key custody;
- external-authenticated session issuance;
- SAML;
- MFA;
- SCIM or automatic provisioning;
- group-to-role mapping.

Each remains a separate reviewed authority transition with fresh merge authorization.

# ADR-138: OIDC runtime/client profile versioning

- **Status:** Accepted
- **Date:** 2026-09-07
- **Decision owners:** MCRI product and engineering
- **Related:** Issue #255, Enterprise Identity 17.1-E; ADR-134; ADR-135; ADR-136; ADR-137

## Context

ADR-134 established server-side authentication sessions. ADR-135 added tenant-scoped enterprise identity providers and explicit bindings to existing application Users. ADR-136 introduced immutable OIDC trust profiles containing issuer, audience, JWKS URI and allowed signing algorithms. ADR-137 then added short-lived authorization transactions with state, nonce and S256 PKCE custody pinned to an exact trust-profile version.

A live OIDC authorization-code flow still needs additional public runtime policy: the authorization endpoint, token endpoint, redirect URI, requested scopes and client authentication method. Reading those values from mutable provider metadata or unreviewed discovery data at callback time would weaken the source lineage already established by ADR-136 and ADR-137.

Combining runtime policy, live IdP redirect, token exchange, JWKS retrieval, ID-token verification and application-session issuance in one change would also make the authentication authority boundary too large to review safely.

## Decision

MCRI will add append-only `OidcRuntimeProfile` records. A runtime profile belongs to exactly one Organization and one enabled OIDC provider and is bound to the provider's exact current `OidcTrustProfile` identity at creation time.

Each runtime profile records only bounded public/runtime policy:

- organization ID;
- provider ID;
- exact trust-profile ID, number and hash;
- monotonically increasing runtime-profile number;
- authorization endpoint;
- token endpoint;
- redirect URI;
- normalized OIDC scopes;
- client-authentication method metadata;
- deterministic runtime-profile hash;
- previous runtime-profile hash; and
- creating application User and timestamp.

Runtime profiles are immutable. Replaying the exact same canonical policy returns the existing row. Any changed runtime policy appends a new version. A trust-profile rotation requires creation of a new compatible runtime profile before new authorization transactions can begin.

## Endpoint and redirect policy

Authorization endpoint, token endpoint and redirect URI must be absolute URIs without embedded credentials or URL fragments.

Outside explicit local/test loopback contexts they must use HTTPS. Local development and test environments may use HTTP only for loopback hosts such as `localhost`, `127.0.0.1` and `::1`.

This tranche does not perform discovery and therefore never replaces pinned endpoints with values fetched from the network.

## Scope policy

The initial scope allowlist is intentionally small:

- `openid` — mandatory;
- `profile` — optional;
- `email` — optional.

`offline_access` is rejected in this tranche because refresh-token custody is not yet designed. Scopes are normalized and persisted in deterministic order for stable hashing and replay detection.

## Client-authentication policy

The bounded metadata allowlist is:

- `none`;
- `client_secret_basic`.

This field describes the future token-endpoint client-authentication method only. No client secret, private key, certificate or other credential is accepted or persisted by this tranche.

## Transaction-source hardening

New `OidcAuthorizationTransaction` rows snapshot the exact runtime profile in addition to the exact trust profile:

- runtime-profile ID;
- runtime-profile number; and
- runtime-profile hash.

Transaction creation fails closed unless the currently governed trust profile has a compatible current runtime profile.

Later runtime-profile or trust-profile rotation does not rewrite an existing transaction. The transaction continues to reference its immutable original source. The internal one-time consume primitive verifies that the referenced runtime-profile record still matches the transaction snapshot and never substitutes a newer runtime profile.

Migration 0091 leaves the new runtime-profile columns nullable at the database level only for compatibility with pre-existing transaction rows. Application code does not create new transactions without a runtime snapshot, and source validation fails closed for a legacy transaction that lacks one.

## Public API boundary

Administrators may manage runtime-profile lineage through tenant-scoped APIs:

- `POST /auth/identity-providers/{provider_id}/oidc-runtime-profiles`
- `GET /auth/identity-providers/{provider_id}/oidc-runtime-profile`
- `GET /auth/identity-providers/{provider_id}/oidc-runtime-profiles`

The existing public transaction-start response may return only the bounded runtime values needed by a future redirect builder together with the exact runtime-profile identity.

No endpoint in this tranche redirects the browser or contacts an IdP.

## Authorization boundary

An OIDC runtime profile grants no application authority.

- No browser redirect is performed.
- No OIDC discovery document is fetched.
- No JWKS is retrieved or cached.
- No authorization code is accepted or exchanged.
- No ID/access/refresh token is accepted, verified or stored.
- No JWT/JWS signature, issuer, audience, nonce or time claim is verified.
- No client secret, private key or certificate is stored.
- No `ExternalIdentityBinding` is created or changed.
- No User is provisioned.
- No tenant is selected from IdP claims.
- No external claim or group changes `User.role`.
- No external-authenticated `AuthSession` is issued.

Application User/Organization state and DB `User.role` remain authoritative.

## Security consequences

### Positive

- live authorization and token endpoints cannot silently drift during a transaction;
- redirect URI and scope policy are explicit and reviewable;
- trust-profile rotation cannot be paired accidentally with stale runtime configuration;
- in-flight transactions retain exact trust and runtime source lineage;
- no new secrets are stored;
- future callback verification can consume a reviewed, immutable runtime snapshot rather than mutable provider metadata.

### Costs

- live OIDC login still does not exist after this tranche;
- administrators must create a compatible runtime profile after trust-profile rotation;
- `client_secret_basic` cannot become operational until a separately governed secret-custody design exists;
- a later tranche still needs redirect construction, token exchange, JWKS retrieval/caching, signed ID-token verification, external-binding resolution and session issuance.

## Deferred

This ADR does not implement:

- browser redirect to the IdP;
- OIDC discovery;
- JWKS retrieval or caching;
- authorization-code or token exchange;
- JWT/JWS signature verification;
- issuer, audience, nonce or token-time validation;
- client-secret/private-key/certificate custody;
- external-authenticated AuthSession issuance;
- automatic User provisioning;
- tenant selection from external claims;
- IdP group-to-role mapping;
- SAML;
- MFA;
- SCIM.

Each remains a separately reviewed authority transition requiring fresh merge authorization.

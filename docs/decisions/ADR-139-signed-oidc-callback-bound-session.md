# ADR-139: Signed OIDC callback verification and bound session issuance

- **Status:** Accepted
- **Date:** 2026-09-07
- **Decision owners:** MCRI product and engineering
- **Related:** Issue #257; ADR-134, ADR-135, ADR-136, ADR-137, ADR-138

## Context

ADR-134 established revocable server-side authentication sessions while keeping application DB User,
Organization and role state authoritative. ADR-135 added explicit tenant-scoped external identity bindings.
ADR-136 pinned immutable OIDC trust policy. ADR-137 added short-lived state/nonce/PKCE authorization
transactions. ADR-138 added immutable runtime/client policy and explicitly deferred live token exchange,
JWKS retrieval, signature verification, binding resolution and external-authenticated session issuance.

The next authority transition must prove a signed external identity without allowing provider claims to
create application users, select tenants, change roles or bypass the existing session assurance layer.
It must also preserve retry safety: a temporary token/JWKS failure must not irreversibly consume the
transaction, while a successful callback must never issue more than one application session.

## Decision

MCRI will activate a bounded **public-client OIDC Authorization Code + PKCE** callback flow.

### Exact pinned authorization source

The authorization request is constructed only from the exact provider, trust profile, runtime profile and
transaction snapshot established before redirect:

- `response_type=code`;
- `client_id` is the pinned trust-profile `audience`;
- exact pinned redirect URI and scopes;
- raw one-time state and nonce returned at transaction creation;
- exact PKCE S256 challenge/method.

No OIDC discovery is performed and reserved authorization parameters may not be pre-populated in the
configured authorization endpoint.

### Public-client code exchange only

The callback accepts the bounded transaction ID, state, nonce, PKCE verifier and authorization code.
Before any provider call, the server revalidates transaction lifecycle, exact pinned source identity and
state/nonce/PKCE proof **without consuming the transaction**.

The code is exchanged only at the exact pinned token endpoint with the exact redirect URI, client ID and
PKCE verifier. Provider HTTP calls do not follow redirects, use bounded timeouts and accept only bounded
JSON responses.

Only runtime profiles with `client_auth_method=none` are operational in this tranche.
`client_secret_basic` remains configuration metadata and fails closed until a separately governed secret
custody mechanism exists.

Refresh-token/offline authority is not enabled. A token response carrying a refresh token is rejected.
Authorization codes, access tokens, ID tokens and refresh tokens are never persisted or audited.

### Signed ID-token verification

The server retrieves verification keys only from the exact pinned JWKS URI; it performs no discovery.
The ID token must:

- use a pinned allowed algorithm, limited to RS256 or ES256;
- identify exactly one compatible signing key by `kid`;
- have a valid cryptographic signature;
- match the exact pinned issuer and audience/client ID;
- contain valid `exp` and `iat` claims and valid `nbf` when present;
- contain a non-empty `sub`;
- contain the original nonce and match it in constant time; and
- when multiple audiences are present, carry `azp` equal to the pinned client ID.

The implementation uses PyJWT with its standard cryptographic backend rather than custom signature code.

### Existing binding is the only account-resolution authority

The verified `sub` is normalized using the existing provider-scoped fingerprint semantics. MCRI resolves
only an existing non-revoked `ExternalIdentityBinding` for the exact transaction tenant/provider.

A session is refused unless:

- the provider remains enabled and matches the transaction snapshot;
- the tenant Organization is active and not deleted;
- the binding exists and is not revoked;
- the bound User belongs to that tenant, is active and is not deleted.

There is no automatic User provisioning, automatic binding, email fallback, tenant selection from token
claims, group-to-role mapping or role elevation. `User.role` in the application database remains the sole
permission role used when MCRI signs its own access token.

### Final one-time authority transition

Only after provider exchange, cryptographic verification and binding resolution succeed does the server
perform the existing locked one-time transaction consume. It then creates a server-side `AuthSession` in
the same database transaction.

OIDC sessions add bounded relational provenance:

- exact external identity provider ID;
- exact external identity binding ID; and
- exact OIDC authorization transaction ID.

The authorization-transaction link is unique, so one transaction can produce at most one application
session. The transaction itself retains the exact trust/runtime profile lineage, avoiding duplicated
configuration snapshots on the session.

Local-password sessions retain null external provenance and their existing behavior is unchanged.

The issued MCRI access token contains the existing server-side session ID and bounded identity provenance
(`src=oidc`, `amr=oidc`), while tenant membership and role still come from the current application User.

## Retry and replay semantics

Provider/JWKS/signature/binding verification occurs before final transaction consumption. A transient
provider failure therefore leaves the transaction unconsumed and retryable while it remains valid.

A callback that reaches the authority boundary must win the locked transaction consume before a session is
created. Concurrent/replayed completion therefore cannot issue a second session; the unique session-to-
transaction constraint is a second database-level safeguard.

## Data minimization and audit

The system never persists or writes to audit logs:

- authorization code;
- access token;
- ID token;
- refresh token;
- raw external subject;
- raw state;
- raw nonce; or
- raw PKCE verifier.

Successful audits contain only bounded IDs, profile hashes/numbers and session provenance. Failed callback
audits contain only a bounded failure category when the transaction tenant can be safely resolved.

## Authorization boundary

External OIDC authentication proves identity only. It does **not** grant claims authority.

`User.organization_id`, Organization/User lifecycle state, `User.role`, claim/evidence tenant isolation and
all human claims-decision guardrails remain authoritative exactly as defined in ADR-134 and subsequent
claims-governance ADRs.

## Consequences

### Positive

- MCRI now has a bounded live OIDC path for pre-bound enterprise users;
- signed identity is verified against immutable trust/runtime/transaction sources;
- transient provider failures do not burn valid transactions;
- replay cannot mint multiple application sessions;
- provider groups/roles cannot become application authority;
- raw provider authentication material is minimized from persistence and audit.

### Costs

- live OIDC requires reachable pinned token and JWKS endpoints;
- cryptographic verification adds the standard PyJWT cryptographic dependency;
- public-client PKCE is the only operational client-auth mode;
- Admins must explicitly pre-create users and external bindings.

## Deferred

This ADR does not implement:

- client-secret/private-key/certificate custody;
- operational `client_secret_basic`;
- refresh tokens or offline access;
- OIDC discovery;
- automatic User provisioning or SCIM;
- email-based account linking;
- IdP group-to-role mapping;
- tenant selection from IdP claims;
- SAML;
- MFA; or
- removal of local-password login.

Each deferred authority transition requires separate scope, tests, ADR and merge authorization.

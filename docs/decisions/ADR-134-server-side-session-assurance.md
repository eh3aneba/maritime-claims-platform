# ADR-134: Server-side session assurance for enterprise identity

- **Status:** Accepted
- **Date:** 2026-09-07
- **Decision owners:** MCRI product and engineering
- **Related:** Issue #247, Enterprise Identity 17.1-A

## Context

MCRI already has tenant-scoped users, database-authoritative organization membership and roles,
Argon2 local-password authentication, signed JWT access tokens, and issuer/audience/expiry checks.
The access token was previously sufficient by itself until expiry, so logout only removed the browser
cookie and there was no server-side way to revoke a captured token.

Phase 17 will later introduce enterprise identity capabilities such as SSO and MFA. Before any external
identity provider is connected, the platform needs an explicit boundary between:

1. **identity proof** — how the user authenticated; and
2. **application authority** — what the user is allowed to do inside a tenant and claim.

That boundary must preserve MCRI's existing tenant isolation and human claims-decision guardrails.

## Decision

MCRI will maintain a server-side `AuthSession` for every issued access token.

A local-password login creates an active session before an access token is returned. The session stores
only bounded identity provenance:

- tenant organization ID;
- application user ID;
- opaque UUID session ID;
- identity source (`local` in this phase);
- authentication method (`password` in this phase);
- creation/expiry timestamps; and
- revocation timestamp, revoking user ID, and a bounded revocation reason when applicable.

The session does **not** store raw passwords, password hashes copied from the user record, JWTs, OIDC or
SAML assertions, IdP credentials, MFA secrets, recovery codes, or other authentication secrets.

Access tokens retain existing `sub`, `org`, issuer, audience, issued-at, not-before, expiry and role
metadata and add:

- `sid` — opaque server-side session UUID;
- `src` — identity source; and
- `amr` — authentication method.

Every authenticated request fails closed unless all of the following are true:

- the token is cryptographically and temporally valid;
- the token carries the required session claims;
- the database User exists, is active, and is not deleted;
- the database Organization exists, is active, and is not deleted;
- the User's database organization matches the token organization;
- the server-side session exists;
- the session belongs to exactly the same User and Organization;
- the session provenance matches the token's source/method metadata;
- the session has not been revoked; and
- the session has not expired.

Logout revokes the exact server-side session before deleting the browser cookie. A captured token for
that session therefore becomes unusable immediately.

An Admin can revoke a specific session only when that session belongs to the Admin's own tenant.
Cross-tenant lookup uses a tenant-scoped query and returns `404`, avoiding both authority and existence
disclosure across tenants. Session lifecycle events are audit logged using bounded identifiers and
metadata only.

A bounded authenticated `/auth/session` endpoint exposes the current session ID, tenant/user IDs,
identity source, authentication method, creation time, and expiry time. It exposes no authentication
secret.

## Authorization boundary

External identity, when introduced, will prove identity only. It will not grant claims authority.

For every authenticated request:

- `User.organization_id` in the application database remains authoritative for tenant membership;
- Organization active/deleted state remains authoritative in the application database;
- User active/deleted state remains authoritative in the application database; and
- `User.role` in the application database remains authoritative for permissions.

Token role metadata and future IdP groups/claims are never used to create, elevate, or replace
application authority. Mapping or provisioning work, if introduced later, must be a separate governed
workflow with explicit application-side controls.

Nothing in this session layer changes claim/evidence tenant isolation or the human authority boundaries
for coverage, causation, fault, liability, fraud, recoverability, legal time-bar effect, reserve,
settlement, payment, closure, evidence admission, correspondence promotion, or canonical claim linkage.

## Consequences

### Positive

- logout and Admin revocation invalidate captured tokens immediately;
- later SSO/MFA work has a safe, provider-neutral session foundation;
- tenant and role authority remain centralized in existing database controls;
- sessions have bounded, auditable identity provenance without storing provider secrets;
- legacy tokens without `sid` fail closed instead of silently bypassing revocation.

### Costs

- authenticated requests require one additional server-side session validation;
- deployments must apply the `auth_sessions` migration before serving tokens issued by this version;
- old pre-deployment access tokens become invalid and users must sign in again.

## Deferred

This ADR does not implement:

- SAML or OIDC redirects, callbacks, discovery, or metadata;
- IdP certificates, client secrets, or raw assertions;
- SCIM;
- MFA enrollment or challenge flows;
- IdP group-to-role mapping;
- automatic user provisioning; or
- removal of local password login.

Those capabilities require separate ADRs and acceptance criteria.

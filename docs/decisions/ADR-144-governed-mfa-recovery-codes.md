# ADR-144: Governed MFA recovery codes

## Status

Accepted for Phase 17.1-K implementation.

## Context

Phase 17.1-I introduced application-controlled TOTP custody and exact-session MFA verification. Phase 17.1-J added disabled-by-default tenant policy and bounded step-up enforcement for sensitive enterprise-identity administration. A user who loses temporary access to the authenticator still needs a pre-issued recovery path that does not introduce support override authority, plaintext secret storage or a second authorization model.

## Decision

Add a bounded set of ten single-use recovery codes tied to the current active confirmed TOTP factor.

Each plaintext recovery code contains 128 bits of random entropy and is revealed only in the successful regeneration response. The application stores only a keyed SHA-256 digest, batch lineage, position and lifecycle state. Plaintext recovery codes must never be persisted or written to audit history.

Recovery-code regeneration:

- requires the same tenant/user as the active confirmed TOTP factor;
- requires the exact current server-side `AuthSession` to already hold MFA verification for that same factor;
- invalidates every prior unused recovery code for the factor in the same database transaction;
- creates a new batch and returns the new plaintext codes exactly once;
- records only bounded, non-secret audit metadata.

Recovery-code verification:

- resolves only against the exact current tenant, user and active confirmed factor;
- locks the matching unused, non-invalidated row for update;
- atomically marks the code consumed and binds consumption to the exact current `AuthSession`;
- marks only that same session as MFA-verified with method `recovery_code` and the same TOTP factor ID;
- rejects replay with the same generic invalid-code response.

A recovery-verified session satisfies the Phase 17.1-J step-up policy only while it remains the exact current valid server-side session and still references the same active confirmed factor.

## Authority boundary

Recovery codes prove possession of a pre-issued recovery credential only. They do not:

- create Users or organizations;
- choose tenant membership;
- change database `User.role`;
- create or alter external identity bindings;
- trust OIDC/SAML attributes, groups or MFA claims as application authority;
- provide support/admin factor reset authority;
- decide any claims coverage, liability, causation, reserve, fraud or settlement question.

Application User/Organization state and database `User.role` remain authoritative on every request.

## Secret-handling boundary

- plaintext recovery codes are returned only at generation/regeneration;
- only keyed one-way digests are persisted;
- audit events contain batch IDs, counts, positions and factor/session IDs only;
- no recovery-code plaintext is accepted in URL paths, query strings, logs or audit payloads;
- regeneration invalidates prior unused codes rather than reusing them.

## Deferred

- support/admin-driven factor reset;
- WebAuthn/passkeys, hardware tokens, SMS/email/push factors;
- external IdP MFA-claim equivalence;
- SCIM/provisioning and IdP group-to-role mapping;
- broader enterprise identity lifecycle automation.

## Validation

The exact PR head must pass backend full suite, Alembic/PostgreSQL preflight, frontend typecheck/build, dependency lock consistency, Docker validation, MT ORION browser E2E, Operational Performance Smoke, Production Deployment Policy and Supply Chain Security. Fresh explicit user authorization remains required before squash merge.

# ADR-143: Governed MFA policy and bounded step-up enforcement

## Status

Accepted for Phase 17.1-J implementation.

## Context

Phase 17.1-I introduced encrypted application-controlled TOTP factor custody and session-level MFA verification provenance, but deliberately did not make MFA mandatory. Enterprise identity now needs a tenant-governed policy that can constrain existing application authority without creating a second authorization model or changing login success semantics.

## Decision

Introduce one tenant-scoped MFA policy record with:

- explicit enabled/disabled state;
- an allowlisted set of existing database User roles to which MFA is required;
- Admin-only read/update control;
- bounded audit history for policy changes.

The policy is disabled by default. No User, role, factor, binding or session is mutated when policy is enabled.

Step-up enforcement is evaluated from the exact current server-side `AuthSession`, the tenant MFA policy, the current database `User.role`, and the current active confirmed TOTP factor. A verified session must reference that same current factor.

The initial protected surface is intentionally bounded to enterprise-identity administration and Admin session revocation:

- `/auth/identity-providers...`
- `/auth/external-bindings...`
- `/auth/sessions/...`
- `/auth/mfa-policy`

Ordinary claim-handling routes and local/OIDC/SAML authentication completion remain unchanged in this tranche.

## Failure semantics

When policy applies to the current role:

- no active confirmed TOTP factor => `mfa_enrollment_required`;
- active confirmed factor but current session not verified with that factor => `mfa_verification_required`.

Both fail closed with HTTP 403 and expose no factor secret, TOTP code, or bootstrap URI.

## Authority boundary

MFA constrains already-existing authority only. It does not:

- create or provision Users;
- select tenant membership;
- change `User.role`;
- create external identity bindings;
- trust OIDC/SAML MFA claims as application TOTP;
- decide any claims coverage, liability, causation, reserve or settlement question.

Application User/Organization state and database `User.role` remain authoritative on every request.

## Deferred

- recovery codes and governed factor recovery/reset;
- WebAuthn/passkeys, hardware tokens, SMS/email/push;
- MFA inside the primary login transaction;
- external IdP MFA claim equivalence;
- per-route policy DSL;
- SCIM/provisioning and IdP group-to-role mapping.

## Validation

The exact PR head must pass backend full suite, Alembic/PostgreSQL preflight, frontend typecheck/build, dependency lock consistency, Docker validation, MT ORION browser E2E, Operational Performance Smoke, Production Deployment Policy and Supply Chain Security. Fresh explicit user authorization remains required before squash merge.

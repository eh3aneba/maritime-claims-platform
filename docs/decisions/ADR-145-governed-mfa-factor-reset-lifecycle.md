# ADR-145: Governed MFA factor reset lifecycle

## Status

Proposed for Phase 17.1-L.

## Context

Phase 17.1-I introduced application-controlled TOTP possession factors, Phase 17.1-J added tenant-governed MFA step-up, and Phase 17.1-K added one-time recovery codes. A user can still lose every usable possession credential. Enterprise support therefore needs a reset path, but a direct administrator reset would be an authority-escalation shortcut and a high-value account-takeover target.

## Decision

MCRI uses an explicit tenant-scoped `MfaFactorResetRequest` lifecycle for support-driven TOTP reset.

A reset request is bound to exactly one existing User and one existing active confirmed TOTP factor. Creation records the requesting Admin, the exact server-side AuthSession and a bounded reason. Only one pending/approved reset may exist for a factor.

The lifecycle is:

`pending -> approved -> executed`

or

`pending -> rejected`

or

`pending -> cancelled`.

Approval is Four-Eyes: the requester cannot approve or reject their own request. Only the requester can cancel a pending request. Tenant boundaries are checked again on every transition.

Execution is fail-closed. The target factor must still be the same active confirmed factor. Execution:

1. invalidates every unused recovery code bound to the target factor;
2. revokes the TOTP factor with reset-request provenance;
3. revokes every still-unrevoked server-side AuthSession for the target user;
4. marks the request executed with actor and session provenance;
5. emits bounded audit metadata without TOTP secret or recovery-code material.

The user must establish a fresh authentication session and explicitly enroll a new factor after reset. Reset never creates or confirms a replacement factor.

When the tenant MFA policy requires MFA for the Admin role, the reset administration surface is protected by the existing exact-session step-up rules.

## Authority boundary

MFA reset removes a compromised or unavailable possession credential; it does not establish identity, create a User, choose a tenant, change `User.role`, create an external identity binding or trust IdP role/group/MFA claims as application authority.

The application database remains authoritative for User/Organization membership and role.

## Security properties

- no direct one-click support reset;
- no self-approval of the same reset request;
- no surviving recovery credential for the reset factor;
- no surviving active server-side session for the affected user;
- no secret/recovery-code material in reset rows or audit events;
- request and execution are tenant scoped and auditable;
- replay of an executed/rejected/cancelled transition fails closed;
- a new factor requires fresh explicit enrollment.

## Out of scope

- password reset;
- support impersonation;
- SMS/email/push recovery;
- WebAuthn/passkeys;
- external IdP MFA-claim equivalence;
- SCIM/provisioning;
- automatic User or external-binding provisioning.

## Consequences

Support recovery requires at least two Admin actors for an executable reset. This creates operational friction by design, but prevents a single compromised Admin session from both requesting and authorizing removal of another user's MFA possession factor.

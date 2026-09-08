# ADR-146: Governed WebAuthn RP profile and registration challenge custody

## Status

Accepted for Phase 17.1-M implementation.

## Context

MCRI already has server-side sessions, governed OIDC and SAML identity, application-controlled TOTP MFA, recovery codes, tenant MFA policy and Four-Eyes factor reset. The next enterprise-identity step is to prepare for WebAuthn/passkey factors without prematurely trusting browser-provided credentials or widening application authority.

A WebAuthn credential cannot be safely treated as an MFA factor until the server has pinned relying-party/origin policy and completed a cryptographically verified registration ceremony. Phase 17.1-M therefore establishes only the policy and challenge-custody half of that ceremony.

## Decision

### Immutable tenant RP policy

Each Organization may have a versioned immutable `WebAuthnRelyingPartyProfile`. A profile pins:

- RP ID
- RP display name
- normalized allowed HTTPS origins
- `user_verification=required`
- `attestation=none`
- deterministic SHA-256 profile hash and lineage

Origins must equal the RP ID host or a subdomain of it. Browser input never selects or overrides RP/origin policy.

### Registration challenge custody

A begin-registration request requires an existing valid application User and exact server-side AuthSession. It creates a short-lived `WebAuthnRegistrationTransaction` bound to:

- Organization
- User
- AuthSession
- exact immutable RP profile ID/number/hash

The challenge is generated from 32 random bytes and returned only in the begin response. Only its SHA-256 digest is persisted. The raw challenge is never audited.

At most one open registration transaction exists per AuthSession. Beginning a new ceremony cancels the prior open ceremony for that exact session before issuing a new challenge.

### Browser creation options

The begin response provides bounded registration material including RP, user handle, timeout, `ES256`/`RS256` public-key credential parameters, `userVerification=required`, resident-key preference and `attestation=none`.

This response is not evidence that a credential exists or is trusted.

### Cancellation

Cancellation requires the same Organization, User and AuthSession that created the transaction. Profile rotation does not rewrite an in-flight transaction: its exact historical profile snapshot remains authoritative for that transaction.

### MFA-sensitive administration

WebAuthn profile administration and registration initiation/cancellation are included in the existing MFA-sensitive authentication surface. When tenant MFA policy applies to the acting role, the current session must already satisfy the existing application-controlled TOTP/recovery assurance requirements.

## Explicit non-goals

Phase 17.1-M does **not**:

- parse or verify WebAuthn attestation objects
- create or trust WebAuthn credentials/public keys
- verify WebAuthn authentication assertions
- mark an AuthSession as WebAuthn-MFA verified
- treat external IdP MFA claims as equivalent application assurance
- provision Users, memberships, roles or external identity bindings
- add SCIM, SMS, email or push MFA

A later separately governed phase must verify the finish-registration ceremony before any WebAuthn credential record can exist.

## Authority boundary

WebAuthn proves possession only after a future cryptographically verified finish ceremony. It never creates application identity or authorization. Database User/Organization state and `User.role` remain the sole application authority for membership and permissions.

## Data minimization

Persisted transaction data contains IDs, immutable profile provenance, challenge digest and lifecycle timestamps. Raw challenge material is response-only and absent from DB/audit. No authenticator attestation, public key or credential ID is stored in this phase.

## Consequences

This split deliberately makes the first WebAuthn phase less feature-complete but prevents a common security failure: accepting a browser credential before RP/origin policy, correlation, replay boundaries and audit provenance are governed. Phase 17.1-N can build the verified registration finish on this source-bound transaction without changing the authority model.

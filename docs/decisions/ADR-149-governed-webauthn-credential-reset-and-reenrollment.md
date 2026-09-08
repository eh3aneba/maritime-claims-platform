# ADR-149: Governed WebAuthn credential reset and one-time re-enrollment

- Status: Accepted
- Date: 2026-09-08
- Phase: 17.1-P
- Issue: #282

## Context

Phase 17.1-N established verified WebAuthn credential custody and Phase 17.1-O established assertion verification that can elevate only the exact existing AuthSession. The existing Four-Eyes MFA reset workflow is intentionally TOTP-specific. Reusing it directly for WebAuthn would widen an established model and create avoidable regression risk.

A second problem exists when a tenant requires MFA and a user loses their only WebAuthn credential. Revoking that credential correctly removes MFA assurance, but the normal WebAuthn registration endpoint also requires MFA policy satisfaction. Without a separately governed recovery transition, the user would be unable to enroll a replacement credential after fresh primary authentication.

## Decision

### 1. Keep TOTP reset unchanged

WebAuthn credential resets use a separate `WebAuthnCredentialResetRequest` lifecycle. Existing TOTP reset/recovery semantics remain unchanged.

### 2. Require Four-Eyes administration

A reset request is tenant-scoped and bound to one active WebAuthn credential and its exact User. The requester and approver must be different active ADMIN users in the same Organization. Requests follow pending, approved, rejected, cancelled and executed states with actor and AuthSession provenance.

### 3. Reset execution is destructive only to existing authentication authority

Execution:

- revokes the exact target WebAuthn credential;
- cancels all open WebAuthn registration transactions for the target User;
- cancels all open WebAuthn authentication transactions for the target User;
- revokes all active server-side AuthSessions for the target User;
- never creates a replacement credential;
- never changes User, Organization, role, external identity binding or claims authority.

### 4. Re-enrollment authorization exists only to prevent last-factor lockout

After the target credential is revoked, the service checks whether any active confirmed TOTP factor or any other active WebAuthn credential remains.

If another factor remains, no re-enrollment authorization is created. The user must satisfy the normal tenant MFA policy with that remaining factor.

Only when no active factor remains does execution create a 30-minute re-enrollment authorization on the executed reset request.

### 5. Re-enrollment authorization is narrow and one-time

The authorization:

- belongs only to the same Organization and User as the reset;
- is available only after fresh primary authentication creates a new valid AuthSession;
- is claimable only while the user still has no active MFA factor;
- becomes bound to the exact fresh AuthSession at WebAuthn registration begin;
- may be reused only by that same AuthSession for a replacement registration retry within the bounded window;
- is consumed only after the ordinary WebAuthn registration finish cryptographically verifies challenge, origin, RP ID, UP/UV, attested credential data and supported public-key structure and successfully creates the replacement credential;
- cannot satisfy WebAuthn assertion verification, administrative MFA, passwordless login, or any non-registration action.

If another MFA factor appears before registration finish, the authorization fails closed.

### 6. Keep raw WebAuthn material out of reset custody

Reset and re-enrollment records never persist or audit raw credential IDs, challenges, `clientDataJSON`, `attestationObject`, authenticator data or signatures. Only internal UUID lineage and bounded timestamps/state are retained.

The registration transaction stores a nullable internal reset-request UUID for provenance. It is deliberately not a database foreign key because reset -> credential -> registration already forms durable relational lineage; adding a reverse FK would create a circular metadata dependency. Service-layer tenant/User/AuthSession/status/expiry checks resolve the UUID fail-closed before a re-enrollment bypass is honored.

## Consequences

- Lost-last-factor WebAuthn recovery no longer creates an MFA-policy dead end.
- Recovery remains an explicit human-governed authority transition rather than an implicit exception.
- Existing TOTP reset/recovery behavior is isolated from this tranche.
- WebAuthn registration cryptography remains authoritative for replacement credential creation; reset approval alone never creates or trusts a credential.
- Passwordless WebAuthn primary login, IdP `amr`/`acr` equivalence, SCIM/provisioning and broader account recovery remain separate future tranches.

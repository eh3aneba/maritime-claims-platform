# ADR-142: Governed TOTP MFA factor custody and session verification

## Status

Proposed for Phase 17.1-I.

## Context

The application now has DB-authoritative Users/Organizations/roles, revocable server-side AuthSessions, explicit external identity bindings, and bounded OIDC and SAML authenticated session issuance. The next enterprise-identity capability is MFA, but making MFA mandatory at the same time as introducing factor custody would combine multiple authority transitions and increase rollout risk.

## Decision

Phase 17.1-I introduces one application-controlled TOTP possession factor per existing User and session-level MFA verification provenance, without changing login or authorization policy.

### Factor custody

- TOTP uses SHA-1, 6 digits and a 30-second period for broad authenticator compatibility.
- A 160-bit secret is generated server-side from cryptographic randomness.
- The plaintext secret and full `otpauth://` bootstrap URI are returned only by the enrollment-start response.
- The persisted secret is AES-GCM encrypted with a unique 96-bit nonce.
- The AES key is domain-separated from the application secret key; authenticated additional data binds ciphertext to the exact Organization and User.
- Only a SHA-256 secret fingerprint may appear in bounded audit metadata. Plaintext secret, TOTP codes and full bootstrap URI must never be persisted or audited.
- Enrollment remains pending until a valid TOTP proves possession.
- Revocation is historical rather than destructive.

### Verification

- TOTP confirmation and session verification are separate transitions.
- Verification binds only to the exact active AuthSession represented by the current authenticated request.
- Successful verification records `mfa_verified_at`, `mfa_method=totp` and the factor id on that AuthSession.
- The factor records the last accepted TOTP time-step and rejects replay or backward reuse of an accepted step.
- A narrow ±1 time-step validation window is allowed for clock skew, but replay protection remains monotonic.

### Authority boundary

MFA proves possession of a factor only. It does not create a User, choose or change tenant membership, alter `User.role`, or grant claims authority. User and Organization active state and DB role remain authoritative on every request.

## Explicitly deferred

- mandatory MFA policy or step-up authorization gates;
- recovery codes and support/admin reset workflows;
- SMS, email, push, WebAuthn/passkeys or hardware-token factors;
- multiple active factors per User;
- treating OIDC/SAML MFA claims as equivalent to application TOTP;
- SCIM or automatic provisioning;
- IdP group/attribute-to-role mapping.

These require separately scoped and authorized tranches.

## Consequences

The platform gains a real possession-factor custody and verification primitive while preserving all existing local/OIDC/SAML login flows. A later phase can add mandatory MFA policy using explicit session assurance state without redesigning identity provenance or silently widening authorization.

## Validation

The exact PR head must pass the standard backend, PostgreSQL/Alembic, frontend, dependency, Docker, MT ORION E2E, operational-performance, production-policy and supply-chain gates; branch must be current with `main`, review threads resolved, and fresh user authorization is required before squash merge.

Refs #25, #247, #263; ADR-134 through ADR-141.

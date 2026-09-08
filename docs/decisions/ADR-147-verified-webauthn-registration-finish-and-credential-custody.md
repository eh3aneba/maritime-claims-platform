# ADR-147: Verified WebAuthn registration finish and bounded credential custody

## Status

Accepted for Phase 17.1-N implementation; merge remains subject to the repository's full validation gates and fresh explicit authorization.

## Context

Phase 17.1-M established immutable tenant WebAuthn RP/origin policy and short-lived registration challenge custody, but deliberately created no credential and granted no MFA assurance. The next authority transition must verify the browser/authenticator registration response against that exact transaction before any public-key credential becomes trusted application data.

## Decision

Phase 17.1-N verifies a bounded WebAuthn registration finish ceremony and persists a credential only after all of the following succeed:

- exact tenant/User/AuthSession/transaction custody and expiry checks;
- `clientDataJSON.type == webauthn.create`;
- SHA-256 match of the response challenge to the stored transaction challenge digest;
- exact origin match against the pinned immutable RP profile;
- `crossOrigin` absent or false;
- authenticator RP ID hash match;
- User Presence, User Verification and Attested Credential Data flags present;
- exact credential ID match between the submitted browser credential ID and authenticator data;
- bounded definite-length CBOR parsing without indefinite lengths or excessive nesting;
- supported COSE public-key structure for ES256/P-256 or RS256/RSA >= 2048 with exponent 65537;
- `fmt=none` with an empty attestation statement.

The service stores only a SHA-256 credential-ID digest, canonical SPKI public key, algorithm, signature counter, AAGUID, attestation format and immutable RP/transaction provenance. Raw credential ID, challenge, `clientDataJSON` and `attestationObject` are never persisted or audited.

Credential-ID digest and registration transaction are unique. The registration transaction is consumed only after successful verification and credential creation. A failed verification leaves the transaction unconsumed so the valid initiating ceremony may still complete before expiry. Credential inventory and explicit revocation are current-user/session scoped and remain protected by the existing tenant MFA-sensitive-auth guard.

## Deliberate boundaries

- WebAuthn authentication/assertion verification is not implemented in this phase.
- Registration does not set `AuthSession.mfa_verified_at`, `mfa_method`, or any other assurance authority.
- No User, Organization membership, role, external identity binding or tenant authority can be created or changed by WebAuthn material.
- Only `fmt=none` is accepted. Packed, TPM, Android, Apple and U2F attestation trust-chain validation remain out of scope instead of being accepted without verification.
- WebAuthn credential reset/recovery integration remains a separately governed lifecycle decision.
- External IdP MFA-claim equivalence and SCIM/provisioning remain separate future tranches.

## Consequences

This creates a verified credential custody primitive suitable for a later WebAuthn assertion-verification tranche while preserving the existing server-side session and database authority boundaries. The application can inventory and revoke verified credentials but cannot yet use them to elevate authentication assurance.

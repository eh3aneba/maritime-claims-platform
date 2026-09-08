# ADR-148: Governed WebAuthn authentication assertion and exact-session MFA assurance

## Status

Accepted for Phase 17.1-O implementation, subject to the repository's normal merge gates and fresh explicit merge authorization.

## Context

Phase 17.1-M pinned immutable tenant WebAuthn relying-party/origin policy and created short-lived registration challenge custody. Phase 17.1-N verified WebAuthn registration ceremonies and persisted only bounded credential provenance: a SHA-256 digest of the credential identifier, canonical SPKI public key, algorithm, signature counter and immutable registration/RP lineage.

The platform now needs to use an already registered WebAuthn credential as an application-controlled MFA step-up for an already authenticated server-side session. This is an authority transition: browser assertion material may strengthen only the exact existing `AuthSession`; it must not create application identity, select tenancy, alter `User.role`, or become a passwordless login path by implication.

## Decision

### 1. Authentication is an exact-session step-up, not primary login

A WebAuthn authentication transaction is bound to one existing active Organization, User, AuthSession and immutable RP profile snapshot. Successful verification may set only that exact session's `mfa_verified_at` and `mfa_method="webauthn"`. The existing application database remains authoritative for User, Organization membership and role.

### 2. Challenge custody remains digest-only

The server generates a cryptographically random 32-byte challenge, returns the base64url challenge once to the browser, and persists only its SHA-256 digest. One open authentication transaction is permitted per AuthSession; beginning a replacement cancels the previous open transaction. Transactions are short-lived and one-time.

Raw challenges are never persisted or audited.

### 3. Discoverable credentials are required for new registrations

Phase 17.1-N deliberately does not persist raw WebAuthn credential identifiers. Therefore the server cannot safely reconstruct `allowCredentials` for later `navigator.credentials.get()` calls. New registration options use `residentKey="required"`, allowing the authenticator/browser to select a discoverable credential without the server retaining the raw credential identifier.

The raw credential identifier returned by the browser during assertion finish is request-only. It is SHA-256 hashed and matched to the stored credential digest.

### 4. Assertions fail closed before any session elevation

Assertion finish verifies all of the following before consuming the transaction or changing session assurance:

- exact transaction Organization, User and AuthSession binding;
- unexpired, uncancelled, unconsumed transaction;
- immutable RP profile snapshot integrity;
- `clientDataJSON.type == "webauthn.get"`;
- exact challenge digest;
- exact pinned allowed origin;
- `crossOrigin` absent or false;
- authenticator RP ID SHA-256 hash;
- User Presence (UP) and User Verification (UV) flags;
- no attested-credential-data or authentication-extension payload in this bounded tranche;
- an existing unrevoked credential owned by the exact Organization and User;
- ES256/P-256 or RS256/RSA>=2048 signature against the stored canonical SPKI public key.

Only after those checks succeed is the exact transaction consumed and the exact AuthSession elevated.

### 5. Signature counters are bounded replay evidence

For authenticators that maintain a non-zero signature counter, a new assertion counter must be strictly greater than the stored value. A zero or regressing value after a non-zero stored counter fails closed.

Authenticators that consistently report zero are supported: `0 -> 0` is accepted without pretending that counter-based clone/replay evidence exists. Transaction one-time custody, challenge freshness and signature verification remain mandatory.

### 6. Credential provenance stays on the assertion transaction

The consumed WebAuthn authentication transaction records only the internal `WebAuthnCredential.id` used for successful verification. `AuthSession` is not given a new credential foreign-key column; it keeps the existing generic MFA timestamp/method fields. This avoids widening session schema while preserving exact auditable credential provenance.

For policy enforcement, a WebAuthn-elevated session is valid only when its matching consumed assertion transaction exists and the referenced credential remains unrevoked. Revoking the credential therefore invalidates that WebAuthn assurance for subsequent MFA-sensitive actions.

### 7. Raw assertion material is transient

The following values are request/response-only and must not be persisted or audited:

- raw authentication challenge;
- raw credential identifier;
- `clientDataJSON`;
- `authenticatorData`;
- assertion signature.

Audit records may contain bounded internal provenance such as transaction UUID, credential UUID, RP profile UUID/number/hash, method and post-verification signature counter.

## Deferred

This tranche deliberately does not add:

- passwordless or primary WebAuthn login;
- User creation or tenant selection;
- role mutation or external-identity binding changes;
- IdP `amr`/`acr` MFA-equivalence trust;
- SCIM or other provisioning;
- authentication extensions;
- broader WebAuthn credential reset/recovery automation beyond separately governed lifecycle work.

## Consequences

WebAuthn can satisfy tenant MFA policy as a cryptographically verified possession/user-verification factor without weakening existing TOTP and recovery-code paths. The platform keeps raw WebAuthn identifiers and assertion material out of durable custody while retaining enough internal provenance to audit exactly which registered credential elevated which server-side session.

# ADR-141: Governed SAML request correlation and bound session issuance

## Status

Accepted for Phase 17.1-H implementation.

## Context

Phase 17.1-G established immutable tenant-scoped `SamlTrustRuntimeProfile` lineage, but intentionally created no live SAML authentication authority. The next transition must add a usable SAML flow without allowing an external IdP assertion to become application authorization authority.

SAML XML signatures also create a distinct wrapping/ambiguity risk: a verifier can validate one signed element while application logic consumes another. The implementation therefore uses a deliberately narrow SAML 2.0 subset rather than attempting broad protocol compatibility in the first live tranche.

## Decision

### One-time request correlation

Each SAML login begins with a short-lived `SamlAuthnTransaction` bound to the exact organization, enabled SAML provider and immutable trust/runtime profile id, profile number and profile hash.

The transaction stores only SHA-256 fingerprints of the generated AuthnRequest ID and RelayState. The raw Request ID and RelayState are response-only material and are not persisted or audited. RelayState contains the transaction UUID plus a high-entropy secret so the ACS can locate the candidate transaction while still requiring possession of one-time proof.

Transactions expire after ten minutes and are consumed exactly once only after signed identity verification and existing-binding resolution succeed. Provider disablement invalidates in-flight authority; later profile rotation does not rewrite an already-started transaction's pinned source.

### AuthnRequest boundary

Only HTTP-Redirect AuthnRequests are generated, and only from the exact pinned profile. The request pins the IdP SSO destination, SP entity ID, ACS URL and HTTP-POST response binding.

The SP does not sign AuthnRequests in this tranche because SP private-key custody is not yet governed. No private signing or decryption key is introduced by Phase 17.1-H.

### Strict signed-Assertion verification

The ACS accepts a bounded base64 SAML Response and parses XML with DTD loading, entity resolution, external network access and huge-tree mode disabled.

The accepted profile is intentionally narrow:

- exactly one direct SAML 2.0 Assertion;
- exactly one XML Signature, directly on that Assertion;
- unique XML `ID` values;
- signature Reference URI exactly `#<that Assertion ID>`;
- exactly the enveloped-signature then exclusive-c14n transforms;
- RSA-SHA256 signature and SHA-256 digest only;
- verification only with the exact X.509 certificate pinned in the transaction's immutable profile;
- certificate fingerprint, RSA key size and current validity rechecked at callback time;
- signed Assertion issuer must equal the pinned IdP entity identifier;
- signed bearer `SubjectConfirmationData` supplies the authoritative `InResponseTo`, recipient and expiry;
- signed Conditions enforce time bounds and exactly one audience equal to the pinned SP entity ID;
- Response issuer, destination, status and `InResponseTo` must also agree, but unsigned Response fields are never used as the sole source of correlation authority.

Encrypted Assertions, alternate signature algorithms, alternate transforms, metadata discovery and broad XML-signature compatibility are out of scope.

### Application authority boundary

The verified NameID is used only to resolve an already-existing active provider-scoped `ExternalIdentityBinding`. The application then resolves the already-existing active User in the same tenant.

SAML attributes and groups are ignored for application authority. They cannot create a User, create a binding, select a tenant, change `User.role` or elevate claims authority. Database User/Organization state remains authoritative.

After verification and binding resolution, the transaction is locked and consumed once, then exactly one `AuthSession` may be created with:

- `identity_source=saml`;
- `auth_method=saml`;
- exact provider id;
- exact binding id;
- exact `saml_authn_transaction_id`.

A unique database constraint prevents more than one session from being linked to the same SAML transaction.

### Data minimization

The application does not persist or audit raw SAML Responses, Assertions, NameID values, AuthnRequest IDs or RelayState values. Audit events contain bounded profile/provider/session provenance and fixed failure categories only.

## Consequences

The platform gains a bounded live SAML path suitable for pre-provisioned enterprise users while preserving the same identity-versus-authorization separation established for OIDC.

Interoperability is intentionally narrower than a general-purpose SAML library. IdPs requiring signed AuthnRequests, encrypted Assertions, non-RSA-SHA256 signatures, nonstandard transforms, metadata discovery or automatic provisioning require separately governed future phases.

## Non-goals

- automatic User or binding provisioning;
- email fallback;
- tenant selection from assertions;
- IdP group/attribute-to-role mapping;
- SAML metadata fetch/discovery;
- SP private/signing/decryption key custody;
- encrypted Assertion support;
- MFA or SCIM lifecycle;
- any claims coverage, causation, liability, reserve, settlement or payment authority.

## Validation gate

The exact PR head must pass the full backend suite, PostgreSQL/Alembic migration chain and preflight, frontend typecheck/build, dependency lock consistency, Docker Compose validation, MT ORION browser E2E, Operational Performance Smoke, Production Deployment Policy and Supply Chain Security. The branch must remain current with `main`, have no unresolved blocking review threads, and receive fresh explicit user authorization before squash merge.

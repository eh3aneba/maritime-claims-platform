# ADR-150: Governed OIDC external MFA assurance equivalence

## Status
Accepted for Phase 17.1-Q implementation and validation.

## Context
MCRI already verifies OIDC authorization-code callbacks against a pinned trust/runtime source and creates an AuthSession only for an explicitly bound, active application User. Tenant MFA policy previously accepted only application-controlled TOTP/recovery and verified WebAuthn assurance.

Enterprise identity providers can emit signed authentication-method (`amr`) or assurance-context (`acr`) claims. Treating any such claim as MFA automatically would widen external identity authority, make mid-flight policy changes ambiguous and allow provider-specific semantics to leak into application permissions.

## Decision
External OIDC MFA equivalence is disabled unless an ADMIN explicitly creates an enabled, immutable assurance profile for one tenant/provider and the exact current OIDC trust profile.

Each profile:
- is immutable and versioned;
- is bound to exact Organization, provider and trust-profile id/number/hash;
- contains bounded accepted `amr` and/or `acr` allowlists;
- normalizes configured AMR values to lower-case exact tokens;
- preserves ACR values as exact strings;
- requires at least one accepted value when enabled;
- is hashed with its full public policy lineage.

At OIDC authorization start, MCRI creates a one-to-one assurance binding for the exact authorization transaction. The binding pins either the current compatible assurance profile or explicit absence of one. A later ADMIN profile rotation cannot change the authority source for an in-flight transaction.

Only claims from the ID token after ordinary signature, issuer, audience, nonce and time validation are eligible for assurance evaluation. Access-token claims, unsigned metadata, role/group claims and generic `auth_method` values are not assurance inputs.

Malformed, absent or non-matching `amr`/`acr` evidence does not fail an otherwise valid OIDC identity login. It only fails to elevate MFA assurance.

When pinned assurance matches:
- the exact callback-created AuthSession receives `mfa_verified_at` and `mfa_method=oidc_external`;
- `mfa_factor_id` remains null because no application-controlled local factor is being asserted;
- the assurance binding records only verification time, evidence type (`amr` or `acr`) and a domain-separated SHA-256 digest of the matched value;
- raw ID tokens, raw AMR/ACR values, authorization codes, nonce and PKCE verifier are not persisted or audited.

Tenant MFA enforcement accepts `oidc_external` only when the exact session, OIDC transaction, provider, trust profile, pinned assurance profile and verification evidence remain internally consistent. Database User/Organization membership and `User.role` remain authoritative.

## Consequences
- Tenants can explicitly recognize their own IdP MFA semantics without creating a generic external-authority bypass.
- Mid-flight configuration changes are deterministic and auditable.
- Existing local TOTP, recovery-code and WebAuthn assurance remain independent.
- An externally assured OIDC session may satisfy mandatory MFA without requiring a local MCRI factor, but only for that exact verified session.
- Disabling or rotating policy does not silently rewrite historical transaction provenance; session revocation remains the explicit mechanism for terminating already-issued sessions when operationally required.

## Explicit deferrals
- SAML AuthnContext equivalence is a separate tranche.
- Passwordless WebAuthn primary login is not introduced.
- IdP-driven User creation, tenant selection, role/group mapping and binding creation remain prohibited.
- SCIM/provisioning remains separately governed.
- No claims, coverage, liability, reserve or settlement authority is affected.

# ADR-135: Governed external identity registry and account binding

- **Status:** Accepted
- **Date:** 2026-09-07
- **Decision owners:** MCRI product and engineering
- **Related:** Issue #249, Enterprise Identity 17.1-B; ADR-134

## Context

ADR-134 established server-side authentication sessions and made the application database authoritative
for tenant membership, user lifecycle and role permissions. Before MCRI can accept a signed OIDC or SAML
authentication result, the application needs a governed way to know which external provider is trusted by
which tenant and which existing application User an external provider subject is allowed to identify.

Adding live redirects, callbacks, client secrets or certificates at the same time would combine trust
configuration, account mapping, secret custody and network authentication into one change. That would make
the authorization boundary harder to review and would increase the risk that external claims accidentally
become application authority.

## Decision

MCRI will first introduce a provider-neutral, tenant-scoped identity registry and explicit account bindings.

An `EnterpriseIdentityProvider` stores only public, bounded configuration:

- tenant organization ID;
- provider key and display name;
- protocol (`oidc` or `saml`);
- public issuer/entity identifier; and
- an explicit enabled/disabled flag.

Providers are created disabled. Only an application Admin in the same tenant may enable or disable them.
No network call, discovery, JWKS fetch, SAML metadata exchange or external session issuance occurs in this
phase.

An `ExternalIdentityBinding` maps one existing application User to one external subject for one provider.
The raw external subject is accepted only at the API boundary. The server strips surrounding whitespace,
combines the value with the opaque provider ID, computes a SHA-256 fingerprint, and persists only that
fingerprint. The raw subject is never stored, returned or written to the audit log.

A provider plus subject fingerprint is permanently unique. A provider plus User may have only one active
binding at a time. Revocation timestamps the existing binding instead of deleting it, so identity history
remains auditable and a later explicit binding may be created for the same User.

## Authorization boundary

External identity registration and binding do not grant application authority.

- A binding can reference only an already-existing User in the same tenant.
- No User is created from an external subject.
- No tenant is selected or changed from an IdP claim.
- `User.role` is never populated or modified from provider groups or claims.
- No external-authenticated `AuthSession` is created in this phase.
- Existing local-password login remains unchanged.
- Cross-tenant provider, User and binding lookup fails closed.

Future signed OIDC/SAML authentication must resolve through this registry and then still pass the
application's database-authoritative User/Organization/session checks before a session can be issued.

## Security consequences

### Positive

- trust configuration is tenant-scoped before any live SSO flow exists;
- raw external subjects are minimized at rest;
- account linking is explicit and auditable;
- provider state can be disabled without deleting historical bindings;
- external claims cannot create or elevate claims authority.

### Costs

- external SSO still cannot be used until a later signed authentication-flow tranche;
- subject fingerprint matching depends on stable provider IDs and exact subject semantics;
- Admins must explicitly maintain bindings for existing Users.

## Deferred

This ADR does not implement:

- OIDC/SAML redirect or callback endpoints;
- signature validation, JWKS retrieval or SAML certificate handling;
- client secrets, private keys or secret-store integration;
- automatic user provisioning or SCIM;
- group-to-role mapping;
- MFA enrollment/challenge;
- local-login removal.

Those require separate review, testing and merge authorization.

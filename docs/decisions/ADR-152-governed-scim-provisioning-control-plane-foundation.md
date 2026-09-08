# ADR-152: Governed SCIM provisioning control-plane foundation

## Status
Accepted for Phase 17.1-S implementation and validation.

## Context
MCRI now supports locally authoritative application Users and Organizations, explicit external identity bindings, OIDC/SAML login, multiple MFA factors and bounded external MFA assurance equivalence. Enterprise deployments also need lifecycle provisioning, commonly through SCIM.

A SCIM credential is materially different from an interactive application session. Treating a provisioning bearer token as a User/Admin session, or accepting IdP/SCIM role and tenant claims as application authority, would collapse the existing authority boundary and create an unsafe path for remote privilege assignment.

## Decision
Phase 17.1-S introduces only the SCIM provisioning **control plane and service authentication boundary**. It does not introduce SCIM-driven User lifecycle mutation.

### Provisioning profiles
A tenant Admin may create an immutable, versioned `ScimProvisioningProfile` for that tenant. Profiles are disabled by default and contain only bounded local configuration:
- client display name;
- fixed MCRI SCIM service base path;
- bounded bearer-token lifetime;
- enabled/disabled state;
- immutable profile lineage and hash.

Creating a new profile version does not rewrite historical profiles. Only the exact current enabled profile can authorize a SCIM bearer credential. Consequently, rotating to a new profile version immediately removes authority from credentials pinned to an older profile, even when the historical credential row itself remains for audit lineage.

### Bearer-token custody
An enabled current profile may receive a high-entropy locally generated bearer token. Plaintext is returned only in the successful issuance response and is never persisted.

MCRI persists only:
- a keyed HMAC-SHA-256 digest using the application secret;
- a short non-secret prefix for operator identification;
- exact tenant/profile lineage;
- creation, expiry and revocation metadata.

At most one unrevoked credential may exist for a profile. Rotation revokes the old credential before the replacement is inserted. Explicit revocation and expiry fail closed. Audit records may contain bounded lineage, token prefix and expiry/revocation metadata, but never the plaintext bearer or keyed digest.

### Service authentication boundary
The SCIM bearer authenticates only a provisioning service context for the exact tenant and exact current profile. It does **not** create an `AuthSession`, impersonate a User, satisfy an application role check, or become an MFA factor.

The Phase 17.1-S SCIM surface exposes only authenticated `ServiceProviderConfig`. User and Group mutation capabilities are not exposed. Capability metadata is intentionally bounded and contains no tenant identifiers, User data or secrets.

Admin management of SCIM profiles and credentials remains behind the existing database-authoritative Admin role and tenant MFA policy. The SCIM service bearer path is separate from interactive application authentication.

### Application authority remains local
Database state remains authoritative for:
- Organization membership and tenant selection;
- User existence and active status;
- `User.role` and application permissions;
- external identity bindings;
- MFA factors and recovery/reset lifecycle.

SCIM/IdP groups, roles, tenant hints or other external attributes do not become application authorization in this tranche.

## Consequences
- Enterprise customers can configure and verify a tenant-pinned SCIM service credential without granting remote User mutation authority yet.
- Credential leakage has a bounded blast radius: exact tenant/profile, expiry, revocation and current-profile checks all must remain valid.
- Token rotation and profile rotation are auditable and fail closed.
- Interactive login/session authority stays independent from provisioning service authentication.
- The next SCIM tranche can add User lifecycle semantics only after this service-auth boundary has proven stable under migration, regression, security and design-partner gates.

## Explicit deferrals
- SCIM `Users` create/update/deactivate/delete.
- SCIM `Groups`.
- external role/group-to-`User.role` mapping.
- IdP/SCIM-driven tenant selection.
- external creation of `ExternalIdentityBinding`.
- password changes, MFA enrollment/reset, recovery operations or session issuance through SCIM.
- any claims, coverage, causation, liability, reserve, settlement, payment or fraud authority.

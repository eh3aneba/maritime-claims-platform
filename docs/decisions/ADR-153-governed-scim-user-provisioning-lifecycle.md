# ADR-153: Governed SCIM User provisioning lifecycle

## Status
Accepted for Phase 17.1-T implementation.

## Context
Phase 17.1-S established a tenant-scoped SCIM service credential and capability-only control plane. Those credentials were deliberately non-mutating. Enabling User provisioning must not silently expand the authority of already-issued credentials, let external SCIM roles/groups become application authority, or let a provisioning client claim an existing local User.

## Decision

1. **Existing SCIM profiles remain non-mutating.**
   - `ScimProvisioningProfile.user_provisioning_enabled` is added with a database default of `false`.
   - User mutation requires a newly pinned current profile with the capability explicitly enabled and a newly issued current token.

2. **Local Admin authorization precedes User creation.**
   - A local Admin creates a short-lived `ScimUserProvisioningGrant`.
   - The grant is pinned to the exact current SCIM profile, normalized email fingerprint, local role and expiry.
   - Grants are one-time, cancellable, tenant-scoped and MFA-sensitive through the existing SCIM Admin control plane.
   - Creating Admin Users through SCIM is prohibited in this tranche. Only claims handler and claims manager roles may be granted.

3. **SCIM payload is attribute input, not application authority.**
   - `roles`, `groups` and tenant hints are not accepted as authority.
   - Application `User.role` comes only from the local grant stored in the application database.
   - `userName` must match the grant fingerprint and becomes immutable for the SCIM-managed resource.
   - Optional `externalId` is stored only as a SHA-256 fingerprint and cannot be added, removed or rebound after creation.

4. **Existing local Users cannot be claimed.**
   - If a local User already exists for the tenant/email, grant creation and SCIM provisioning fail closed.
   - Phase 17.1-T does not create `ExternalIdentityBinding`; SCIM provisioning remains separate from OIDC/SAML subject binding.

5. **SCIM-created local password material is unusable externally.**
   - User creation generates high-entropy random password material and stores only the normal application password hash.
   - The plaintext is never returned, persisted separately or audited.

6. **SCIM management is lineage-bounded.**
   - `ScimUserBinding` records the tenant, consumed grant, creation profile lineage, userName fingerprint and optional externalId fingerprint.
   - SCIM reads expose only Users with this explicit binding in the token's tenant.
   - Local-only Users are not enumerated by the SCIM User surface.

7. **Updates are deliberately narrow.**
   - Full replace may synchronize display name and active state only.
   - Role, tenant, userName and externalId lineage cannot be changed through SCIM.
   - PATCH, Groups, password change and bulk remain unsupported.

8. **Deprovisioning is controlled deactivation, not deletion.**
   - `active=false` and `DELETE /Users/{id}` set the application User inactive and record deactivation lineage.
   - All active `AuthSession` rows for the User are revoked immediately with reason `scim_deprovisioned`.
   - Repeated deactivation is idempotent.
   - Reactivation may restore `is_active` but cannot change role, MFA factors or external identity bindings.

9. **Application authority remains local.**
   - Database Organization membership and `User.role` remain authoritative.
   - SCIM never determines claims, coverage, causation, liability, reserve, settlement, payment or fraud outcomes.

## Consequences
- Enabling User provisioning requires an explicit profile rotation and token rotation after deployment.
- Provisioning automation has a local human authorization checkpoint for each new User.
- SCIM can safely drive bounded lifecycle sync without becoming tenant or role authority.
- Automatic role/group mapping and SSO subject binding remain separate future tranches.

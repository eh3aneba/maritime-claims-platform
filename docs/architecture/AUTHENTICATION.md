# Authentication & Tenant Security — Sprint 2 Phase D

## Identity model

MVP login uses `organization_slug + email + password` because user email uniqueness is scoped to an organization. Passwords are stored only as Argon2 hashes.

## Token model

- JWT access token signed by the API.
- Token contains user id, organization id and role.
- Browser login also receives the token in a HttpOnly, SameSite=Lax cookie.
- The backend **does not authorize from the token organization claim alone**. It reloads the user from the database and verifies the stored `organization_id` matches the signed token context.
- Production/staging cookies use the `Secure` flag.

## Roles in MVP

- `admin`
- `claims_manager`
- `claims_handler`

Only administrators can create users in Phase D.

## Tenant isolation rule

Every protected domain query must constrain both the resource id and the authenticated user's organization id. Example:

```sql
WHERE claims.id = :claim_id
  AND claims.organization_id = :current_organization_id
  AND claims.deleted_at IS NULL
```

The `get_claim_for_tenant` helper is the first reusable enforcement primitive and will be used by Claims API routes in Phase E.

## Logout limitation

Phase D uses stateless access tokens. Logout clears the browser cookie; server-side revocation/refresh-token rotation is deferred until an operational need is demonstrated.

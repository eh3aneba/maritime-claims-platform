# Security foundation

This document is a living engineering checklist, not a security certification.

## Implemented through Sprint 2 Phase G

- Secrets are environment-driven; no production secret belongs in source control.
- Passwords use Argon2 hashes and are never stored as plaintext.
- Login identity is scoped by organization slug + email.
- JWT access tokens carry user/organization context, but database membership and role remain authoritative.
- Browser sessions can use a HttpOnly, SameSite=Lax cookie; staging/production cookies are `Secure`.
- Backend tenant isolation is mandatory: domain queries constrain `organization_id` as well as resource id.
- Current-user checks reject inactive/deleted users and inactive/deleted organizations.
- Roles implemented: admin, claims manager, claims handler.
- User creation is admin-only and cannot target another organization.
- Authentication/user-management actions are audit logged where an authenticated identity exists.
- File metadata includes hashes for integrity/duplicate controls.
- No sensitive document contents should be written to application logs.
- Soft-delete and traceability rules preserve claim history.

- Claim evidence uses server-generated storage keys rather than user filenames.
- Uploads are size/type/signature validated and SHA-256 hashed during streaming.
- Duplicate evidence inside a claim is rejected by hash.
- Document list/download/delete operations are claim- and tenant-scoped.
- Evidence deletion is soft; underlying bytes are retained during the MVP for audit.
- Upload, download and delete actions are audit logged.

## Verified security tests

- Organization-aware login works.
- Same email can exist in different organizations without ambiguous authentication.
- Forged organization context in a signed token is rejected when it conflicts with database membership.
- Forged role text inside a token does not elevate privileges because database role is authoritative.
- A claim lookup for Organization B returns no resource when executed under Organization A context.
- Inactivating an organization invalidates existing authenticated access on the next request.
- Claims handlers cannot use the admin user-creation endpoint.

## Before first external pilot

- Threat model and abuse cases
- CSRF review for final browser deployment topology
- Refresh-token/session revocation decision
- Rate limiting and login brute-force controls
- Dependency and secret scanning in CI
- Backup/restore test
- File malware scanning strategy
- Penetration test
- Data-processing agreement templates
- Security headers and production reverse-proxy configuration

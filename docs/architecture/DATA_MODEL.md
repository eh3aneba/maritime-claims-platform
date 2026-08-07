# Database foundation v1.0

Sprint 2 / Phase C introduces the first persistent domain model.

## Foundation tables

- `organizations` — tenant boundary and customer organization
- `users` — authenticated organization members and roles
- `vessels` — organization-scoped vessel master records
- `claims` — H&M machinery claim header / lifecycle state
- `documents` — claim document metadata and integrity hash
- `audit_logs` — immutable security/business audit events

## Key design rules

1. All tenant-owned business records carry `organization_id`.
2. Tenant isolation is enforced in backend queries in the authentication/API phases.
3. Public-facing claim references are separate from UUID primary keys.
4. Claim money uses `NUMERIC`, never floating-point columns.
5. Application timestamps are timezone-aware and stored in UTC operationally.
6. Claims and documents support soft deletion; audit logs do not.
7. Reserve history will become a dedicated append-only table in a later phase; the claim header currently stores only the current snapshot.
8. File bytes remain outside PostgreSQL; `documents` stores metadata, hash and storage key.
9. Sprint 3 adds `ai_runs` and `document_extractions`; they remain a candidate/review layer and never replace the authoritative claim record automatically.

## Relationship sketch

```text
organizations
  ├─ users
  ├─ vessels
  │    └─ claims
  │         └─ documents
  └─ audit_logs
```

## Migration

Initial revision:

`0001_database_foundation`

Run inside `apps/api`:

```bash
alembic upgrade head
```

Inspect generated SQL without touching a database:

```bash
alembic upgrade head --sql
```

# Sprint 2 — Software foundation

## Phase A — Architecture
Status: Complete

## Phase B — Repository & Development Environment
Status: Complete

Deliverables:
- Monorepo structure
- Next.js starter
- FastAPI starter
- Docker Compose
- PostgreSQL 18.4 service
- Environment template
- Health endpoint
- Architecture/security documentation

## Phase C — Database Foundation
Status: Complete

Implemented:
- SQLAlchemy 2 models
- Alembic configuration
- Initial migration `0001_database_foundation`
- `organizations`
- `users`
- `vessels`
- `claims`
- `documents`
- `audit_logs`
- Tenant-scoped indexes and constraints
- Soft deletion on claims/documents/master records
- Immutable audit-log shape
- Database metadata tests

## Next: Phase D — Authentication

Planned:
- Password hashing
- Login/logout/current-user endpoints
- JWT/session strategy
- Role enforcement
- Organization context
- Tenant-protected repository queries

## Phase D — Authentication & Tenant Security

- Organization-aware login
- Argon2 password hashing
- JWT access tokens + HttpOnly browser cookie
- `/auth/login`, `/auth/logout`, `/auth/me`
- Admin-only user creation
- Role authorization foundation
- Database-authoritative organization context
- Claim tenant-security helper
- Cross-tenant isolation tests

# Sprint 2 — Software Foundation

## Sprint goal

Build the secure non-AI application foundation required before claim evidence can be processed by OCR/LLMs.

## Phase A — Architecture
Status: Complete

- Next.js / TypeScript frontend
- FastAPI / Python backend
- PostgreSQL primary datastore
- Modular monolith
- Docker-based deployment boundary

## Phase B — Repository & Development Environment
Status: Complete

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

- SQLAlchemy 2 models
- Alembic configuration
- Initial migration `0001_database_foundation`
- `organizations`, `users`, `vessels`, `claims`, `documents`, `audit_logs`
- Tenant-scoped indexes and constraints
- Soft deletion on domain records
- Immutable audit-log shape

## Phase D — Authentication & Tenant Security
Status: Complete

- Organization-aware login
- Argon2 password hashing
- JWT access tokens + HttpOnly browser cookie
- `/auth/login`, `/auth/logout`, `/auth/me`
- Admin-only user creation
- Role authorization foundation
- Database-authoritative organization context
- Cross-tenant isolation tests

## Phase E — Claims API
Status: Complete

- Tenant-scoped claim create/list/detail/update
- Atomic human-readable claim reference generation
- Search/filtering
- Handler assignment controls
- Claim workflow state machine
- Reserve update audit control
- Vessel API required for claim creation

## Phase F — Claims Frontend UI
Status: Complete

- Login
- Dashboard
- Claims portfolio
- Create H&M machinery claim
- Create/select vessel
- Claim overview
- Workflow advancement
- Reserve control

## Phase G — Document & Evidence Foundation
Status: Complete

- Drag-and-drop multi-file claim upload UI
- Actual browser upload progress
- PDF/JPG/PNG/DOCX/XLSX validation
- Configurable file-size limit (25 MB default)
- Basic file-signature validation
- Streaming SHA-256 calculation
- Duplicate detection within a claim
- Server-generated tenant/claim/document storage paths
- Persistent local Docker evidence volume
- Tenant-scoped list/download/soft-delete endpoints
- Evidence download and removal UI
- Audit events for upload/download/delete
- Soft deletion retains evidence bytes for audit

## Sprint 2 Definition of Done

The product can now complete this non-AI workflow:

```text
Login
  -> create/select vessel
  -> create H&M machinery claim
  -> open claim
  -> upload evidence
  -> verify evidence metadata/hash
  -> list/download/remove active evidence
```

Backend automated test suite at Sprint close: **34 passing tests**.

## Next — Sprint 3: AI Document Intelligence

First target flow:

```text
Chief Engineer Report.pdf
  -> queued processing
  -> text extraction / OCR fallback
  -> document classification
  -> document-specific structured fact extraction
  -> source attribution + confidence
  -> human approve/edit/reject
  -> approved claim facts
```

AI remains decision support; the secured original document remains the evidentiary source of truth.

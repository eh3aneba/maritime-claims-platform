# Maritime Claims & Risk Intelligence Platform

Monorepo for the H&M Machinery Claims MVP.

## Current status

Sprint 2 is complete through Phase G:

- Next.js + TypeScript claims UI
- FastAPI modular-monolith backend
- PostgreSQL 18.4 + SQLAlchemy/Alembic
- Organization-aware authentication and backend tenant isolation
- Claim/vessel APIs, workflow state machine and audit controls
- Secure claim evidence upload/list/download/soft-delete APIs
- SHA-256 duplicate detection, file-size/type/signature validation
- Tenant-separated persistent local evidence storage with an S3-compatible migration boundary
- Claim Documents UI with drag-and-drop, upload progress and evidence actions

**Sprint 2 foundation is now complete.** OCR, AI classification, structured extraction, RAG and predictive features remain intentionally deferred until Sprint 3, where they will operate on top of the secured evidence source-of-truth.

## Prerequisites

- Git
- Docker + Docker Compose (recommended)
- Node.js 22+ for running the web app outside Docker
- Python 3.12+ for running the API outside Docker

## Quick start with Docker

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- Web: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- API health: http://localhost:8000/api/v1/health

## Apply database migrations

With the stack running:

```bash
docker compose exec api alembic upgrade head
```

Or locally:

```bash
cd apps/api
alembic upgrade head
```

Inspect migration SQL without connecting:

```bash
cd apps/api
alembic upgrade head --sql
```

## Run backend tests

```bash
cd apps/api
pytest
```

## Repository structure

```text
apps/
  api/      FastAPI modular monolith + SQLAlchemy/Alembic
  web/      Next.js frontend
infra/      infrastructure notes/scripts
docs/       product, architecture, ADRs
scripts/    helper scripts
```

## Architecture guardrails

1. Business logic stays in the backend, not the frontend.
2. Frontend never accesses PostgreSQL directly.
3. AI will not directly modify approved claim data.
4. Tenant isolation will be backend-enforced.
5. Files are stored outside the relational database.
6. Sensitive changes are audit logged.
7. Money uses decimal database types; timestamps are timezone-aware.
8. MVP remains a modular monolith.

## Bootstrap the first organization admin

After applying the database migration, create the initial organization and administrator with environment variables rather than a public registration endpoint:

```bash
cd apps/api
MCRI_BOOTSTRAP_ORG_NAME="Demo Marine Insurer" \
MCRI_BOOTSTRAP_ORG_SLUG="demo" \
MCRI_BOOTSTRAP_ADMIN_EMAIL="admin@example.com" \
MCRI_BOOTSTRAP_ADMIN_PASSWORD="replace-with-a-strong-password" \
python -m app.modules.auth.seed
```

Then authenticate through `POST /api/v1/auth/login` with organization slug, email and password.

## Sprint 2 Phase E — Claims API

The backend now supports tenant-scoped claim creation, listing, search/filtering, detail retrieval, core edits, controlled handler assignment, status transitions, reserve audit updates, and atomic human-readable claim reference generation for PostgreSQL.

Core claims endpoints live under `/api/v1/claims`.

## Sprint 2 Phase F — Claims UI

The web application now includes organization-aware login, a claims dashboard, claims portfolio, H&M machinery claim creation, vessel creation, and a claim overview page connected to the tenant-safe FastAPI endpoints.

Frontend routes:

- `http://localhost:3000/login`
- `http://localhost:3000/dashboard`
- `http://localhost:3000/claims`
- `http://localhost:3000/claims/new`

The backend also exposes tenant-scoped `GET/POST /api/v1/vessels` endpoints required by claim creation.


## Sprint 2 Phase G — Document Evidence

Claim pages now support secure evidence handling. The backend exposes tenant-scoped document list/upload/download/soft-delete endpoints. Files are persisted outside PostgreSQL using server-generated storage keys, SHA-256 hashes are calculated while streaming uploads, duplicates within a claim are rejected, and basic file signatures are validated. Upload/download/delete actions are audit logged.

The web claim overview includes drag-and-drop multi-file upload, document type/confidentiality metadata, actual upload progress, evidence listing, download and soft removal.

Sprint 3 begins with AI Document Intelligence: `uploaded evidence -> text/OCR -> classification -> structured facts -> human review`.

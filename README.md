# Maritime Claims & Risk Intelligence Platform

Monorepo for the H&M Machinery Claims MVP.

## Current status

Sprint 2 / Phase D is complete:

- Next.js + TypeScript web app
- FastAPI backend
- PostgreSQL 18.4 via Docker Compose
- SQLAlchemy 2 domain models
- Alembic migrations
- Tenant foundation and backend-enforced tenant isolation
- Claim/vessel/document/audit foundation
- Environment configuration
- Health endpoint
- Organization-aware authentication (organization slug + email + password)
- Argon2 password hashing and JWT access tokens
- HttpOnly auth cookie support
- Role enforcement for admin / claims manager / claims handler
- Admin-only user creation
- Cross-tenant claim access guard
- Architecture and security ADRs

Claims business APIs are implemented in the next Sprint 2 phase. AI remains intentionally deferred until Sprint 3.

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

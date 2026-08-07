# Maritime Claims & Risk Intelligence Platform

Monorepo for the H&M Machinery Claims MVP.

## Current status

Sprint 2 / Phase C is complete:

- Next.js + TypeScript web app
- FastAPI backend
- PostgreSQL 18.4 via Docker Compose
- SQLAlchemy 2 domain models
- Alembic migrations
- Tenant foundation
- Claim/vessel/document/audit foundation
- Environment configuration
- Health endpoint
- Architecture and security ADRs

Authentication and business APIs are implemented in the next Sprint 2 phases. AI remains intentionally deferred until Sprint 3.

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

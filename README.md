# Maritime Claims & Risk Intelligence Platform

Starter monorepo for the H&M Machinery Claims MVP.

## Sprint 2 / Phase B status

This repository establishes the development foundation only:

- Next.js + TypeScript web app
- FastAPI backend
- PostgreSQL 18.4 via Docker Compose
- Environment configuration
- Health endpoint
- Dockerfiles
- Architecture decision records

Claims, authentication, database models, and document upload are implemented in later Sprint 2 phases.

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

## Local API without Docker

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Local web without Docker

```bash
cd apps/web
npm install
npm run dev
```

## Repository structure

```text
apps/
  api/      FastAPI modular monolith
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
7. Money uses decimal types; timestamps use UTC.
8. MVP remains a modular monolith.

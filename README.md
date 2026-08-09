# Maritime Claims & Risk Intelligence Platform

Monorepo for the H&M Machinery Claims MVP.

## Current status

The MVP now includes the full H&M Machinery / Turbocharger design-partner workflow:

- Core claims platform, tenant isolation, audit and secure evidence handling
- Source-linked document intelligence and human AI review
- Engine-log chronology and deterministic evidence-conflict detection
- Missing-document rules, tasks and controlled document-request workflow
- Maintenance/workshop and financial intelligence
- Versioned, source-linked Initial Assessment builder
- MT ORION end-to-end regression pilot with P0 findings closed
- Claims-handler usability hardening and equivalent-evidence workflow
- Design-partner deployment preflight, deterministic demo seed, browser E2E spec and backup/restore baseline

**Current phase: Sprint 5D — Design Partner Readiness.** The repository is prepared for a controlled private walkthrough. A private pilot is not production certification.

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

## Sprint 3 Phase A — Document Processing Foundation

Background document processing, page/sheet-aware text extraction, and the provider-neutral AI gateway are active.

## Sprint 3 Phase B — Chief Engineer Report Intelligence

The backend now supports an explicit background AI job for Chief Engineer Reports. It persists versioned `ai_runs` and source-linked `document_extractions`, separates facts from source opinions, verifies source quotes against extracted segments, and leaves every candidate in `pending` human-review state.

`AI_PROVIDER=disabled` remains the default. The OpenAI adapter uses strict Structured Outputs and requires explicit `AI_MODEL` and `OPENAI_API_KEY` configuration. Restricted documents are not sent to that external provider unless separately enabled.

## Sprint 3 Phase C — Human AI Review

The web app now includes an AI Review queue with source preview, confidence, fact/opinion separation, individual Approve/Edit/Reject actions and cautious bulk approval for low-risk verified metadata.

The backend adds append-only `ai_feedback`, current `claim_facts`, review/audit APIs, source-verification safeguards, and `GET /api/v1/claims/{claim_id}/facts`. Opinions/inferences and sensitive decision fields cannot be promoted into authoritative claim facts.

## Sprint 3 Phase D — Engine Log Intelligence

The backend now supports the `ai_extract_engine_log` durable job and strict `engine_log_v1` schema for source-order machinery events. Date/time, RPM, load, turbocharger speed, exhaust temperature, lube-oil pressure, alarms, shutdown/restart, actions and remarks are stored as source-linked extraction candidates. Measurements preserve raw wording and receive non-destructive numeric normalization when possible.

Engine-log event fields are intentionally not promoted into scalar `claim_facts`; human-reviewed repeatable evidence will feed the Chronology Engine instead. Claim Documents UI can now queue CE Report or Engine Log intelligence after text extraction completes.

## Current milestone

Sprint 5 Phase D: Design Partner Readiness. The private synthetic pilot runbook, deployment preflight, demo seed, browser E2E specification and backup/restore baseline are included.

## Design-partner pilot

For a private synthetic walkthrough:

```bash
cp .env.pilot.example .env
# Replace every REPLACE_WITH_* value
./scripts/design_partner_preflight.sh .env
```

Then open `http://localhost:3000/login` using the demo organization/email/password from `.env`.

Detailed instructions:

- `docs/pilot/DESIGN_PARTNER_RUNBOOK.md`
- `docs/pilot/DESIGN_PARTNER_TEST_SCRIPT.md`
- `docs/security/PILOT_SECURITY_CHECKLIST.md`
- `docs/operations/DEPLOYMENT_CHECKLIST.md`
- `docs/operations/BACKUP_RESTORE.md`

The `demo-seed` compose profile populates the synthetic MT ORION case deterministically and never calls an external AI provider.


## Design Partner Cohort
Founder GTM tooling lives under `/api/v1/outreach` and the `/outreach` UI. See `docs/gtm/` for cohort qualification, outreach cadence, and the controlled paid-pilot offer.

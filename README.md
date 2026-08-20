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
- Quarantine-first evidence upload with ClamAV admission scanning and fail-closed handling
- Controlled legacy-evidence rescan, scanner-error retry and audited administrative purge
- Human-approved FNOL intake with fail-closed malware scanning, local English/Persian OCR and deterministic field proposals
- Controlled immutable evidence versions with preserved superseded history and quarantine-safe replacement
- Unified source-linked Evidence Matrix across approved facts, document versions and active conflicts
- Controlled Correspondence Centre with Manager/Admin review and manual external-dispatch recording
- Versioned Advanced Financial Adjustment Controls for PA, GA, Sue & Labour and RDC line treatment
- Controlled Settlement & Payment Ledger with approved-adjustment sourcing and four-eyes authorization
- Consent-gated Controlled Email Intake with human claim linking and retention controls
- Least-privilege Email Provider Adapter Operations with bounded run and retention ledgers
- Claim-scoped External Collaboration Portal with expiring hashed invitations and human-reviewed submissions
- Time-boxed private-pilot execution with bounded case measurements, accountable P0–P3 product gaps and an immutable human outcome
- Human-attested production architecture baseline across nine domains that preserves missing/partial controls and never claims certification
- Versioned implementation evidence and independent four-eyes verification for all nine production architecture controls
- Expiring external-AI staging activation with three independent reviews, per-document eligibility and a runtime kill switch
- Version-pinned AI benchmark promotion with deterministic quality/safety/cost thresholds and immutable failures
- Bounded real-document private AI pilot with independent data-owner approval, quotas, mandatory human review and incident rollback
- Measured private-pilot exit gate with workflow scorecards, cost/incident trends and three independent reviews

**Current phase: Sprint 11D — Measured Private-Pilot Exit.** A completed 11C pilot can now be assessed against fixed workflow coverage, human action, usefulness, effort, latency, cost and incident thresholds. Product, Quality and Risk must independently approve before an Admin records an exit recommendation. The recommendation is not Production authorization; Production-wide use and Restricted documents remain blocked.

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

The Compose stack starts an internal-only ClamAV service for evidence admission scanning. Allow roughly 3–4 GB of available memory for ClamAV signature loading and do not publish its unauthenticated port `3310` outside the Compose network.

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
python -m pip install --require-hashes -r requirements-dev.lock
pytest
```

## Reproducible dependencies

Install committed dependencies from lockfiles rather than resolving new versions during each build:

- API production and Docker: `apps/api/requirements.lock`
- API tests: `apps/api/requirements-dev.lock`
- Browser E2E: `tests/browser/requirements.lock`
- Web application: `apps/web/package-lock.json` with `npm ci`

The Python lockfiles include package hashes, and CI rejects stale lockfiles. Edit the input manifests (`requirements.txt`, `requirements-dev.in`, or `package.json`) rather than editing generated lockfiles manually. Dependabot checks Python, npm, browser and GitHub Actions dependencies every week.

## Supply-chain security

The independent supply-chain workflow audits Python and web production dependencies, scans complete Git history for committed secrets, and scans final API/web Docker images for high or critical vulnerabilities on every pull request and weekly. It also publishes a seven-day SPDX JSON SBOM artifact for each run.

See `docs/security/DEPENDENCY_SECURITY.md` for the enforcement policy, finding-handling rules and local commands.

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

Claim pages now support secure evidence handling. The backend exposes tenant-scoped document list/upload/download/soft-delete endpoints. New uploads are first written under a server-generated quarantine key, checked for extension/type/signature consistency and duplicates, then streamed to ClamAV. Only a clean verdict promotes the bytes into active evidence storage and queues document processing. Detected malware and scanner failures remain outside the active claim file with an audit record and no download endpoint.

Existing evidence created before this control is preserved as `legacy_unscanned`; it is not falsely relabelled as clean. Development may explicitly disable scanning for trusted synthetic files, while pilot/staging/production preflight requires `MALWARE_SCAN_ENABLED=true`.

Administrators and Claims Managers can queue bounded background rescans for legacy evidence. A clean verdict promotes the record to `clean`; malware or scanner failure moves the bytes into logical/physical quarantine and blocks downloads and all worker processing. Scanner-error quarantines can be retried explicitly. Only an Administrator can permanently purge retained bytes, with an exact record confirmation and mandatory audit reason; infected evidence has no release endpoint.

The web claim overview includes drag-and-drop multi-file upload, document type/confidentiality metadata, actual upload progress, evidence listing, download and soft removal.

Sprint 3 begins with AI Document Intelligence: `uploaded evidence -> text/OCR -> classification -> structured facts -> human review`.

## Sprint 3 Phase A — Document Processing Foundation

Background document processing, page/sheet-aware text extraction, and the provider-neutral AI gateway are active.

## Sprint 3 Phase B — Chief Engineer Report Intelligence

The backend now supports an explicit background AI job for Chief Engineer Reports. It persists versioned `ai_runs` and source-linked `document_extractions`, separates facts from source opinions, verifies source quotes against extracted segments, and leaves every candidate in `pending` human-review state.

`AI_PROVIDER=disabled` remains the default. The OpenAI adapter uses strict Structured Outputs and requires explicit `AI_MODEL` and `OPENAI_API_KEY` configuration. Sprint 11A permits synthetic/de-identified OpenAI use only in staging. Sprint 11C adds the narrower real-document path, which also requires active 11B promotion, a separately approved private pilot and per-document eligibility. Restricted documents remain blocked.

## Sprint 3 Phase C — Human AI Review

The web app now includes an AI Review queue with source preview, confidence, fact/opinion separation, individual Approve/Edit/Reject actions and cautious bulk approval for low-risk verified metadata.

The backend adds append-only `ai_feedback`, current `claim_facts`, review/audit APIs, source-verification safeguards, and `GET /api/v1/claims/{claim_id}/facts`. Opinions/inferences and sensitive decision fields cannot be promoted into authoritative claim facts.

## Sprint 3 Phase D — Engine Log Intelligence

The backend now supports the `ai_extract_engine_log` durable job and strict `engine_log_v1` schema for source-order machinery events. Date/time, RPM, load, turbocharger speed, exhaust temperature, lube-oil pressure, alarms, shutdown/restart, actions and remarks are stored as source-linked extraction candidates. Measurements preserve raw wording and receive non-destructive numeric normalization when possible.

Engine-log event fields are intentionally not promoted into scalar `claim_facts`; human-reviewed repeatable evidence will feed the Chronology Engine instead. Claim Documents UI can now queue CE Report or Engine Log intelligence after text extraction completes.

## Current milestone

Sprint 11A adds the separately authorized provider control plane; Sprint 11B requires measured synthetic/de-identified promotion evidence; Sprint 11C adds the organization/data-owner decision for a small real non-restricted cohort; Sprint 11D freezes measured cohort outcomes and independent exit reviews. These stages remain content-minimizing, and none provisions a provider key or grants Production authorization.

Next, Sprint 11E will design a separately authorized limited-production evaluation control plane with environment isolation, allowlists, rollout caps, monitoring, expiry and rollback. Production-wide and Restricted-document AI remain unauthorized. Full English/Persian UI localization remains deferred until the product reaches a stable post-evaluation stage.

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

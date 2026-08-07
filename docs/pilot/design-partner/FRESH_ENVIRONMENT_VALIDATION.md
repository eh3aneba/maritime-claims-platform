# Fresh Environment Validation — Sprint 5 Phase E

## Executive result

Repository hardening and fresh-process validation are complete within the available execution environment. Three deployment defects were found and fixed. The core backend, deterministic MT ORION demo, standalone worker, authentication, API restart persistence, migrations, scripts, and source validation pass.

A controlled external design-partner session remains **NO-GO until three host-runtime gates pass on a workstation with Docker and network/package access**:

1. Fresh Docker production build.
2. Next.js production build.
3. Browser E2E against the running application.

These gates could not be executed in the current environment because Docker is absent, the npm registry is unreachable/unavailable, and Playwright Chromium is not installed and cannot be downloaded due network DNS restrictions.

## Fresh-environment defects found and fixed

### FRESH-001 — Standalone CLI sessions were unbound

**Impact:** `preflight`, `demo-seed`, bootstrap admin, and document worker used `SessionLocal()` without an engine bind. FastAPI requests were unaffected because `get_db()` bound the engine, which hid the defect in request-level tests.

**Fix:** added `create_session()` to the database session layer and migrated all standalone processes to use it.

**Regression coverage:** `test_create_session_binds_configured_engine`.

### FRESH-002 — Standalone worker did not register all ORM models

**Impact:** the worker could fail with SQLAlchemy relationship resolution errors such as `Organization` not found when run as its own process.

**Fix:** the worker imports the central ORM metadata registry before querying jobs.

**Regression coverage:** `test_standalone_worker_registers_all_orm_models`.

### FRESH-003 — Default demo email was rejected by API validation

**Impact:** `manager@pilot.test` is rejected by `EmailStr` because `.test` is a reserved special-use domain. Browser/API demo login therefore could not succeed with the documented default credentials.

**Fix:** changed the synthetic demo identity consistently to `manager@demo.mcri.app` across seed defaults, Compose, pilot env example, browser E2E, and pilot tests. The design-partner preflight now performs a real demo login and MT ORION API lookup after seeding.

**Regression coverage:** `test_default_demo_email_is_login_schema_compatible`.

## Gate results

| Gate | Result | Evidence |
|---|---|---|
| Fresh ZIP extraction | PASS | Phase D package extracted into a clean directory |
| Backend test suite | PASS | 119/119 tests with third-party pytest plugin autoload disabled |
| MT ORION deterministic seed | PASS | 1 claim, 9 documents, 1 assessment; second seed created no duplicate |
| Application preflight | PASS | Executed as a standalone process against persisted validation DB |
| Standalone worker startup | PASS | `python -m app.workers.document_worker --once` exited successfully |
| API health | PASS | HTTP 200 from `/api/v1/health` |
| Demo authentication | PASS | `manager@demo.mcri.app`, Claims Manager |
| MT ORION API visibility | PASS | One `MCRI-DEMO-MT-ORION` result after authenticated login |
| API restart persistence | PASS | Claim and USD 575,000 reserve remained visible after kill/restart |
| PostgreSQL migration SQL | PASS | Offline upgrade 0001→0014 and downgrade 0014→0013 generated successfully |
| Compose YAML | PASS | Parsed successfully |
| Shell scripts | PASS | `bash -n` validation |
| Restore destructive guard | PASS | Restore refused without `MCRI_RESTORE_CONFIRM=YES` |
| Frontend TS/TSX syntax | PASS | 23 files, 0 parser syntax errors |
| Fresh Docker build | BLOCKED | Docker/Podman not installed in current environment |
| Next.js production build | BLOCKED | npm internal registry returned 404; public registry DNS returned EAI_AGAIN |
| Browser E2E | BLOCKED | Chromium binary absent; Playwright download failed with EAI_AGAIN |
| Live PostgreSQL backup/restore | BLOCKED | No Docker/PostgreSQL runtime or pg_dump/pg_restore available |

## Restart simulation

A persisted file-backed validation DB was seeded with the deterministic MT ORION scenario. The API was started as a separate Uvicorn process, authenticated through HTTP, and MT ORION was retrieved. The process was terminated and restarted against the same DB. Authentication and claim retrieval succeeded again with:

- External reference: `MCRI-DEMO-MT-ORION`
- Claim reference: `MCRI-HM-2026-0001`
- Current reserve: `USD 575,000`

SQLite was used only as an execution fallback for the process/restart simulation because a PostgreSQL runtime is not available in this environment. PostgreSQL remains the supported deployment database; its migration SQL was validated separately.

## Strengthened design-partner preflight

`./scripts/design_partner_preflight.sh .env` now performs six steps:

1. Validate Docker Compose.
2. Build/start database, API, worker, and web.
3. Run application preflight.
4. Seed deterministic MT ORION.
5. Check API and web health.
6. Perform real demo login and assert MT ORION is visible through the authenticated Claims API.

This sixth step would have caught the invalid demo-email defect before any browser walkthrough.

## External design-partner Go/No-Go

Current status: **NO-GO on this environment; CONDITIONALLY READY for a connected pilot host.**

Before an external walkthrough, run on the actual host:

```bash
cp .env.pilot.example .env
# Replace every REPLACE_WITH_* value.
./scripts/design_partner_preflight.sh .env
python tests/browser/design_partner_e2e.py
./scripts/backup_postgres.sh
```

The session is GO only if:

- Docker build/start succeeds.
- Next.js production build succeeds.
- Browser E2E succeeds.
- A real PostgreSQL backup is produced and non-empty.
- Restart preserves the seeded claim and evidence access.

## Remaining deployment limitations

This validation does not constitute production certification. The pilot still lacks SSO/SAML, malware scanning, centralized secret management, HA object storage, penetration testing, and production-grade backup automation. External AI remains disabled for the deterministic design-partner demo by default.

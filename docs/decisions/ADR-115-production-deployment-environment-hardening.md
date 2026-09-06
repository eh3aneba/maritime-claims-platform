# ADR-115 — Production deployment configuration is fail-closed and separate from demo validation

## Status
Accepted as the Phase 14.3 design under #207. The implementation is not part of `main` until its pull request passes the exact-head verification gate and receives fresh explicit merge authorization.

## Context
The platform already has a runtime preflight for pilot, staging and production environments. That preflight rejects the known local database password, the default application secret, wildcard credentialed CORS and non-HTTPS staging/production CORS origins. Phase 14.1 added dependency-aware health semantics and Phase 14.2 added a bounded live-stack performance smoke.

Two deployment gaps remained:

1. `NEXT_PUBLIC_API_BASE_URL` using plain HTTP in a shared environment produced only a warning, so an externally exposed production frontend could be built against an unsafe public API origin; and
2. the shared secret check recognized the exact default value and minimum length but did not reject recognizable demo, test, CI-only or replacement placeholder material that happened to be long enough.

The repository also contains `scripts/design_partner_preflight.sh`. That script intentionally seeds the deterministic MT ORION demo and verifies a demo login. Its purpose is design-partner acceptance, not production attestation. Treating that flow as the production gate would blur an important environment boundary.

## Decision

### 1. Production deployment configuration fails closed
When `APP_ENV=production`, the application preflight applies a dedicated production deployment policy in addition to the existing database, CORS, malware-scanning, storage and AI-governance checks.

Production requires:
- `SECRET_KEY` to contain at least 32 characters;
- `SECRET_KEY` not to match a narrow deny-list of recognizable replacement, demo, test or CI-only placeholder markers;
- `NEXT_PUBLIC_API_BASE_URL` to be explicitly set;
- the public API base URL to be an absolute HTTPS URL;
- the public API base URL not to contain embedded credentials;
- the public API hostname not to be localhost, an IP loopback, an example/reserved hostname or the deterministic demo hostname; and
- the existing HTTPS-only production CORS rule to remain in force.

The validator is deliberately a **narrow safety gate**, not a secret-strength or entropy oracle. Secret generation, storage, rotation and compromise response remain deployment/operations responsibilities.

### 2. Validation output is configuration-metadata only
A failed production policy names the affected configuration key and the violated rule. It does not interpolate or echo:
- the supplied secret;
- database credentials;
- embedded credential values;
- request or response bodies;
- claim identifiers or claim text;
- evidence/document content;
- correspondence;
- legal analysis; or
- insurance analysis.

Regression tests explicitly verify that rejected secret material is absent from returned error messages.

### 3. Design-partner validation remains a separate non-production path
`.env.example` remains a development/design-partner starting point and intentionally contains local URLs and replacement values. It is explicitly documented as **not** being a production template.

`scripts/design_partner_preflight.sh` remains unchanged in purpose: it can start the Docker stack, seed deterministic demo data and verify the demo login/MT ORION journey. Passing that script does not attest that a production environment is safe.

Production operators must instead supply real deployment configuration with `APP_ENV=production` and pass both:

```bash
python -m app.core.deployment_policy
python -m app.core.preflight
```

The normal Compose `preflight` service also invokes the embedded production policy when `APP_ENV=production`.

### 4. CI attests the policy without storing deployment secrets
A dedicated `Production Deployment Policy` GitHub Actions workflow imports only the dependency-light policy helper and validates:
- a synthetic safe HTTPS production configuration; and
- representative fail-closed cases for a known placeholder secret, plain HTTP and localhost.

Synthetic safe secret material is assembled at runtime from deliberately low-entropy fixture fragments rather than committed as a secret-looking literal. The full backend suite separately covers the detailed positive/negative matrix and preflight integration.

### 5. Claims authority remains unchanged
This deployment policy is infrastructure safety only. It creates no new claims-domain state, recommendation or decision authority.

It does not create or change coverage, causation, fault, liability, fraud, recoverability, governing-law, legal time-bar effect, reserve, settlement, payment or claim-closure authority. Canonical Claim Facts, Recovery/Time-Bar, Initial Assessment, Correspondence and Claim Pack boundaries remain unchanged.

## Consequences

### Positive
- unsafe public API transport becomes a production blocker instead of a warning;
- recognizable demo/test/CI placeholder secrets cannot pass merely because they are long enough;
- production validation is explicit and independently visible in CI;
- the deterministic design-partner journey stays usable; and
- configuration failures remain content-free and safe for ordinary deployment logs.

### Trade-offs and residual risks
- the placeholder matcher is intentionally narrow and cannot prove that a secret has strong entropy;
- this tranche does not choose a cloud provider, secret manager, IaC framework, certificate automation or deployment platform;
- TLS termination and certificate validity still depend on the selected deployment infrastructure;
- actual production secrets must be generated, stored and rotated outside source control; and
- future environment/provider-specific controls should extend this gate rather than weaken or bypass it.

## Verification gate
The Phase 14.3 pull request is merge-ready only when, on the exact pull-request head:
- backend full suite is green, including production-policy regression tests;
- Production Deployment Policy CI is green;
- PostgreSQL migration/application-preflight is green;
- frontend typecheck/build is green;
- Docker Compose and dependency-lock validation are green;
- relevant MT ORION browser acceptance remains green;
- Supply Chain Security is green;
- the branch is not behind `main`;
- there are no unresolved review blockers; and
- fresh explicit user authorization has been given for the Phase 14.3 PR.

Refs #207
Refs #202

# Design Partner Deployment Checklist

## Build and configuration

- [ ] `.env.pilot.example` copied to `.env` and placeholders replaced.
- [ ] `docker compose config` succeeds.
- [ ] `migrate` service completes successfully.
- [ ] `preflight` service completes successfully.
- [ ] API health is `200` at `/api/v1/health`.
- [ ] Web login returns `200`.
- [ ] Worker is running.

## Demo validation

- [ ] `demo-seed` completes without external AI.
- [ ] MT ORION appears once and seed is idempotent on second run.
- [ ] Browser E2E passes.
- [ ] Screenshot artifact is retained for the build under test.

## Data safety

- [ ] Backup taken before schema upgrade.
- [ ] Evidence volume backup procedure confirmed.
- [ ] Synthetic-only label shown/communicated for the demo dataset.
- [ ] No real customer evidence is loaded without explicit approval.

## Go / no-go

Go for a controlled design-partner walkthrough only if all checklist items pass. A private design-partner walkthrough is not equivalent to production readiness.

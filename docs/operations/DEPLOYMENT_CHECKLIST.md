# Design Partner Deployment Checklist

## Build and configuration

- [ ] `.env.pilot.example` copied to `.env` and placeholders replaced.
- [ ] `docker compose config` succeeds.
- [ ] `migrate` service completes successfully.
- [ ] `preflight` service completes successfully.
- [ ] `clamav` is healthy and port `3310` is not published to the host/public network.
- [ ] `MALWARE_SCAN_ENABLED=true` and `CLAMAV_HOST=clamav` in the pilot environment.
- [ ] Host capacity includes roughly 3–4 GB available memory for ClamAV signature loading.
- [ ] API health is `200` at `/api/v1/health`.
- [ ] Web login returns `200`.
- [ ] Worker is running.
- [ ] Worker image contains `tesseract`, `eng`/`fas` language data and `pdftoppm`.
- [ ] `OCR_ENABLED`, `OCR_LANGUAGES`, `OCR_MAX_PAGES` and `OCR_TIMEOUT_SECONDS` are explicitly reviewed.

## Demo validation

- [ ] `demo-seed` completes without external AI.
- [ ] MT ORION appears once and seed is idempotent on second run.
- [ ] Browser E2E passes.
- [ ] A known-clean synthetic file uploads and shows `Malware scan · Clean` before processing.
- [ ] An EICAR test file is blocked in an isolated test claim and appears only in the quarantine panel; remove it according to the operator retention procedure after validation.
- [ ] A Claims Manager queues a bounded legacy rescan and the worker records clean/quarantine outcomes.
- [ ] Scanner-error retry is tested after scanner recovery and releases only after a clean verdict.
- [ ] Administrative purge is tested only with synthetic evidence and retains the audit/provenance record.
- [ ] A clean synthetic English FNOL reaches `pending_review` without creating a Claim.
- [ ] A clean synthetic Persian image/PDF reaches `pending_review` through local OCR.
- [ ] Approving the same intake twice returns the same Claim and creates only one source Document.
- [ ] Rejecting an intake creates no Claim and retains the review audit trail.
- [ ] Screenshot artifact is retained for the build under test.

## Data safety

- [ ] Backup taken before schema upgrade.
- [ ] Evidence volume backup procedure confirmed.
- [ ] Synthetic-only label shown/communicated for the demo dataset.
- [ ] No real customer evidence is loaded without explicit approval.
- [ ] Legacy records labelled `legacy_unscanned` are identified and accepted for the walkthrough or covered by a controlled rescan plan.
- [ ] The operator has reviewed `docs/operations/EVIDENCE_QUARANTINE.md` and assigned quarantine investigation ownership.

## Go / no-go

Go for a controlled design-partner walkthrough only if all checklist items pass. A private design-partner walkthrough is not equivalent to production readiness.

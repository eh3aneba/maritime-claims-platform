# Design Partner Deployment Checklist

## Build and configuration

- [ ] `.env.pilot.example` copied to `.env` and placeholders replaced.
- [ ] `docker compose config` succeeds.
- [ ] `python scripts/pilot_compose_port_policy.py --env-file .env` passes before any stack startup; rendered DB (5432), API (8000) and Web (3000) host ports must bind **127.0.0.1 only**; no other Compose service may publish a host port or use host networking. This checks Compose port declarations, not external firewall/proxy exposure or readiness.
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

## Read-only operational service-status snapshot

After an authorized operator has started a **synthetic-only** isolated Pilot stack from the reviewed candidate, collect a privacy-safe Docker Compose service observation. This tool never invokes `up`, `exec`, `stop` or `restart`; it runs only `docker compose ps --all --format json` and **does not print raw container output, configuration, environment, customer labels or error text**:

```bash
python scripts/pilot_compose_readiness.py \
  --env-file .env \
  --release-sha "<exact-current-candidate-40-char-SHA>" \
  --output /secure/pilot-releases/rc-001-compose-status.json
```

It requires **11** known services: DB, ClamAV, API and Web must be running **and healthy**; the document, governance, scheduling, observation and review projector workers must be running (and not explicitly unhealthy); migration and preflight must have exited with code zero. A present optional `demo-seed` must have exited successfully. Missing, duplicate or unknown services, incomplete one-shot work, explicit unhealthy states, malformed/unavailable Docker responses or a reused output filename **fail closed**. Only fixed service names, enum states/health, zero-exit flags, counts, a supplied release SHA and the UTC observation timestamp go into the new exclusive JSON.

A passing observation is **only** container-status metadata, not proof that the candidate SHA is actually deployed or that the images match immutable digests. It does not establish a clean-host deployment, private firewall/proxy exposure, authenticated user journey, ClamAV scanning behavior, SFTP acceptance, matched database + Evidence recovery point, rollback rehearsal, alert ownership, human signoff or Pilot GO. All those independent P0 acceptance records under #653 remain required. A failed snapshot is a blocking operational signal, not permission to disable checks or skip a service. Keep this record in controlled operator storage, not the public repository.

### Automated synthetic-stack readback in CI

The `Operational Performance Smoke` workflow now runs the read-only Compose readiness checker **after** its isolated, synthetic `design_partner_preflight.sh` stack startup and **before** performance measurements. It saves `artifacts/compose-readiness.json` in the short-retention `operational-performance-smoke` artifact and fails the required operational performance gate if any one of the 11 mandated service statuses is missing, not ready, duplicated or unexpected. The script cannot make a failing stack pass by running `docker compose up` or otherwise changing state. The recorded SHA is the workflow's candidate-head SHA supplied by CI, not an independently proven running image identity.

**Evidence boundary:** this is a real Docker Compose observation on an ephemeral GitHub runner using synthetic data, but **not** a fresh private host deployment rehearsal, human monitoring ownership, scanner-malware behavioral proof, externally durable storage proof, matched DB/Evidence restore, rollback or operator acceptance. An artifact-bearing green workflow is necessary code-side validation only; #653 still requires actual independent operational exercises and human signoff. Keep the CI artifact free of secrets, customer hostnames, container names, raw environment or claim/Evidence bodies.

### Synthetic-only live malware scanner behavior

The Operational Performance Smoke workflow performs a bounded, **real ClamAV daemon** scan after confirming all 11 synthetic Compose services are ready. The CI-only helper `scripts/pilot_live_clamav_probe.py` invokes the existing API container using `docker compose exec -T api python -` and passes a fixed synthetic program through stdin; it never alters the application image. In an environment explicitly labeled `APP_ENV=test` with scanning enabled, it proves the existing production `ping_clamd` and `scan_file` functions accept one harmless text fixture (`clean`) and recognize the harmless EICAR antivirus test string (`infected`). Both temporary files are removed within the API container; the tool stores no customer bytes, filenames, scanner error details, threat names, raw Docker output or secrets.

```bash
python scripts/pilot_live_clamav_probe.py \
  --env-file .env.performance \
  --release-sha "<exact-ci-candidate-sha>" \
  --output /secure/pilot-releases/rc-001-clamav-synthetic.json
```

A failure to reach the daemon, scan safely, detect EICAR, or return exact metadata fails the **required operational performance gate** before its performance budget measurement. The evidence artifact is an exclusive minimal JSON summary, not a real customer-malware report. This only validates a **synthetic CI environment**. It does **not** establish approved production malware signatures, quarantined customer files, real operator response, storage durability, backup/recovery, fresh-host deployment, or Pilot GO; those remain separate P0 operational obligations under #653. EICAR is a non-malicious scanner test signature, not an actual infection.

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
- [ ] For recovery drills, PostgreSQL dump and an independently captured Evidence archive are hash-bound using `scripts/pilot_recovery_pair.py`, with the quiescence/change-record reference; a successful integrity record alone does **not** establish a consistent recovery point or successful restore.
- [ ] Synthetic-only label shown/communicated for the demo dataset.
- [ ] No real customer evidence is loaded without explicit approval.
- [ ] Legacy records labelled `legacy_unscanned` are identified and accepted for the walkthrough or covered by a controlled rescan plan.
- [ ] The operator has reviewed `docs/operations/EVIDENCE_QUARANTINE.md` and assigned quarantine investigation ownership.

## Go / no-go

Go for a controlled design-partner walkthrough only if all checklist items pass. A private design-partner walkthrough is not equivalent to production readiness.

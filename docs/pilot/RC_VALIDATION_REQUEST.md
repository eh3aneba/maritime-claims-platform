# Protected-main synthetic release validation request

Request: 2026-11-24-001

Purpose: execute the complete synthetic CI validation suites on the exact protected-main merge SHA of this request, including the first manual MT ORION rehearsal. The push event is intentionally path-scoped to changes of this file. Existing PR checks remain mandatory; all existing workflows still support manual dispatch.

This is a test request, not a release approval, environment attestation, deployment, or authorization for real customer data. AI, OCR and SFTP remain disabled in the first-manual pilot rehearsal. The candidate identity must be read from the resulting main commit and independently compared with each run's head SHA. A failing, skipped, canceled, or absent required execution is not accepted. Do not edit this request merely to mask failures; investigate failed jobs first. A later explicitly authorized request uses a distinct request identifier in a new protected PR.

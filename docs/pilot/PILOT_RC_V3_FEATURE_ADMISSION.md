# Pilot v1 Release Candidate v3 — Feature and Evidence Admission

**Status: documentation and structural check only.** This is not a Pilot GO decision, real-source OCR validation, or local AI authorization. Source: [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653); Pilot scope [#647](https://github.com/eh3aneba/maritime-claims-platform/issues/647).

## Why v3

Earlier `mcri-pilot-rc-v2` had a required SFTP feature choice but did not require explicit installed/deployed mode selection for self-hosted AI inference or *critical* Persian OCR extraction. A syntactically complete record could therefore omit these risks. The v3 gate **rejects v1/v2 records**, refuses implicit defaults and requires explicit actual-runtime evidence owned by an operator. Migration is manual and evidence-based, not a blind conversion of prior proof flags.

## Selected feature modes

Each mode must be explicitly `enabled` or `disabled`, with a related evidence reference, owner and observed UTC timestamp; drafts start `pending`.

| Feature | Enabled | Disabled |
| --- | --- | --- |
| `sftp_ingestion` | `real_sftp_governed_lifecycle=pass` with controlled real-server lifecycle evidence | `not_applicable` with observed runtime disablement and ingestion controls |
| `ai_inference` | `local_ai_independent_acceptance=pass` with pinned/attested model identity, isolated network runtime, expert-reviewed synthetic source fidelity and human-governance evidence | `not_applicable` with observed disabled provider and no customer document inference/egress |
| `persian_critical_extraction` | `persian_critical_ocr_acceptance=pass` with independent bilingual original-source verification on unseen H&M examples, negative-control scope, technical terms, dates and source/page hashes | `not_applicable` with recorded exclusion of **machine-derived critical Persian conclusions** from the selected pilot workflow and review of originals by qualified humans |

**Important:** `persian_critical_extraction=disabled` does not mean the product cannot display a Persian document or retain a machine transcript; it means no critical H&M fact/negation, timestamp, causation or coverage inference may be automatically accepted from that OCR path. This decision needs a deployable enforcement configuration and an accountable operator verification. Merely writing `disabled` in JSON is not enforcement. An independent Pilot GO decision must validate the configuration against the actual running stack.

Two additional proofs are always `pass` (never `not_applicable`) even if AI/SFTP/Persian critical extraction are all disabled:

- `actual_feature_flag_enforcement`: verify the exact deployed image SHA, environment/configuration contract, effective flags, disabled connectors and absence of unauthorized AI or document egress.
- `source_discrepancy_review_and_resolution_policy`: demonstrate an accountable manual path for reporting an unresolved OCR discrepancy, withholding dependent approvals, preserving original/hash/version and old human decisions, and independent revalidation or de-scoping. The existing reporting/warning API is not expert adjudication. Follow [#850](https://github.com/eh3aneba/maritime-claims-platform/issues/850).

## Operator workflow (private evidence store only)

1. Decide a narrowly scoped H&M machinery pilot configuration **before** generating a release candidate. Default product direction is authenticated manual upload; SFTP/email/Drive/AI are not approved merely by a successful CI build.
2. From a controlled repository checkout, after independently verifying its exact SHA, create a *new* private record, e.g.
   `python -m scripts.pilot_rc_gate init --release-sha <exact-40-character-sha> --output <new-private-path>/pilot-rc.json`
3. Choose all three `features` values in the private record. For each conditional and unconditional `proofs` entry, attach a **real** evidence reference, independent observer/owner and actual canonical UTC observation timestamp. Disabled features need proof with `result=not_applicable`, **not** omitted evidence.
4. Record the exact Alembic head, image digests (including Postgres and ClamAV), configuration and known-limitations references. Capture fresh-host, migration, deployment, backup+matched storage restore, rollback, monitoring, onboarding and six exact-head workflow results; do not reuse an unrelated PR's green checks.
5. Run `python -m scripts.pilot_rc_gate check <private-path>/pilot-rc.json --expected-sha <independently-verified-40-character-sha>`. A structural PASS means only that fields are present and shaped correctly. It cannot attest image provenance, external reviewer identity, security posture, actual model identity or semantic correctness.
6. Require separate source-review, operations, security/privacy and product-owner authorization **before** any real-data pilot. The pipeline never grants it automatically.

Do not commit completed pilot records, customer names, private endpoints, evidence text, reviewer credentials, real scan images or secrets to this repository. Maintain a separate confidential audit trail with source/version and dated decision provenance.

## Current blockers

- [#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810): Persian negation and original-source accuracy require independent verification or formal de-scope.
- [#752](https://github.com/eh3aneba/maritime-claims-platform/issues/752): self-hosted AI still synthetic-only; model identity, network isolation and expert review not attested for customer use.
- [#850](https://github.com/eh3aneba/maritime-claims-platform/issues/850): unresolved source-discrepancy review/resolution policy is not an automatic machine correction.
- [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653): actual fresh-host, restore, rollback, monitoring and operator rehearsal not signed off.

**Real-data Pilot = NO-GO until independently approved.**

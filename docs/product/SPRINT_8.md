# Sprint 8 — Intake, Evidence Operations and Interoperability

## Phase A — Human-approved FNOL intake and local OCR

Goal: reduce manual case opening without allowing extraction software or AI to create authoritative claim data.

Delivered scope:

- Quarantine-first PDF/JPG/PNG/DOCX notification intake with mandatory ClamAV verdict.
- Durable worker processing and bounded local Tesseract OCR in English and Persian.
- Deterministic generic document classification and source-linked field proposals.
- Tenant-scoped review UI with explicit vessel matching and editable claim fields.
- Human approval/rejection notes, audit events and idempotent one-claim creation.
- Clean source promotion into the existing evidence model without automatic Claim Facts.

Acceptance guardrails:

- Upload, OCR and classification never create a Claim.
- No coverage, causation, liability, fraud, reserve or settlement conclusion is automated.
- External AI remains disabled and receives no intake evidence.
- Infected/scanner-error items never enter active evidence or document processing.
- Existing approved Claim Facts and assessment snapshots are never rewritten.

## Phase B — Controlled evidence document versioning

Goal: allow corrected or updated evidence to become current without overwriting the claim file's historical record or transferring human approvals.

Delivered scope:

- Explicit tenant- and claim-scoped document families with monotonic version numbers.
- Human-initiated replacement requiring a reason and an existing current source version.
- Signature validation, duplicate protection and the existing quarantine-first ClamAV gate.
- Atomic active-version transition only after clean evidence admission.
- Preserved downloads, provenance and source links for superseded versions.
- Clear UI labels for current and superseded versions and a warning that approvals do not transfer.
- Audit events for direct replacement and clean quarantine-retry release.
- Rule-driven missing-document checks use only the current version; historical reviewed evidence remains preserved.

Acceptance guardrails:

- Replacement creates a new evidence record and never overwrites prior bytes or metadata.
- Infected/scanner-error replacements do not change the current version.
- Approved Claim Facts, chronology, financial review and assessments remain attached to their original sources.
- No AI selects an authoritative version and no external AI receives evidence.
- Cross-tenant and cross-claim replacement attempts remain hidden.

## Next phases

1. Unified Evidence Matrix across technical, chronology, financial and rule review.
2. Controlled PDF/Excel claim-pack exports.
3. Email/correspondence ingestion only after provider, consent and retention controls are designed.

The complete ordered capability backlog is tracked in GitHub issue #25.

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

## Next phases

1. Evidence document version linking and replacement workflow.
2. Unified Evidence Matrix across technical, chronology, financial and rule review.
3. Controlled PDF/Excel claim-pack exports.
4. Email/correspondence ingestion only after provider, consent and retention controls are designed.

The complete ordered capability backlog is tracked in GitHub issue #25.

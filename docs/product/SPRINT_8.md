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

## Phase C — Unified source-linked Evidence Matrix

Goal: give claim handlers a single professional view of approved facts, supporting sources, document-version state and active conflicts without creating a second source of truth.

Delivered scope:

- Read-time tenant-scoped Matrix with Topic / Fact / Supporting Evidence / Conflicting Evidence / Status.
- Fact column limited to current human-approved Claim Facts.
- Authoritative and deterministic corroborating source grouping with locator, quote and document version.
- Active conflicts attached by source extraction, with unlinked conflicts preserved as conflict-only review rows.
- Explicit warnings when an approved fact still cites superseded evidence.
- Claims-native UI and MT ORION browser regression coverage.
- No AI call, automated truth selection or mutation of facts, chronology or approved assessments.

Acceptance guardrails:

- Opinions, inferences and pending AI candidates never populate the Fact column.
- Conflict state remains a human review state, not a finding about which source is true.
- Replacing evidence never transfers approval.
- No causation, coverage, liability, fraud or settlement determination is generated.

## Phase D — Controlled PDF/Excel claim-pack exports

Goal: let authorized claim handlers create portable point-in-time claim packs without allowing exported files to hide unresolved review state or drift with later claim changes.

Delivered scope:

- Canonical tenant-scoped snapshot shared by PDF and XLSX renderers.
- Human-approved Claim Facts and source-version provenance through the Evidence Matrix.
- Conspicuous open conflicts, outstanding evidence, open actions and financial flags.
- Latest approved Initial Assessment only; pending sections and draft versions remain excluded.
- Immutable snapshot/file SHA-256 hashes, protected storage and export history.
- Explicit review-aid acknowledgement and clear non-decision disclaimer.
- Audited generation and download with cross-tenant/cross-claim hiding.
- MT ORION browser generation/download regression coverage.

Acceptance guardrails:

- Export does not mutate live Claim Facts, chronology, rules, financial review or assessments.
- Pending AI candidates never populate factual sections.
- No automated coverage, causation, liability, fraud, reserve, recoverability or settlement determination.
- Failed generation never registers or exposes a partial file.
- No external AI receives evidence.

## Next phases

1. Policy and Contract Intelligence with issue spotting only.
2. Email/correspondence ingestion only after provider, consent and retention controls are designed.

The complete ordered capability backlog is tracked in GitHub issue #25.

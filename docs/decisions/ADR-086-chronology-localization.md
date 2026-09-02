# ADR-086 — Chronology localization remains presentation-only

## Status
Accepted for Phase 12K Chronology increment.

## Context
The claim Chronology combines human-reviewed, source-linked evidence into a deterministic operator timeline and exposes evidence conflicts for human review. The surface contains both controlled UI language and source-derived content such as event titles/descriptions, document names, field values, source quotes, timestamps, conflict values and human-authored resolution notes.

English/Persian localization must make the operator workflow usable in RTL without changing chronology semantics or creating an impression that translated presentation is new evidence.

## Decision
1. Localize only controlled UI labels, help text, metrics, empty/error states, materiality/status labels, measurement display labels and human action labels.
2. Do not auto-translate event titles, event descriptions, source quotes, document names, evidence values, conflict source values or existing human resolution notes.
3. Keep claim references, source filenames, dates, times, timezone labels, technical field labels and numeric/engineering values directionally isolated where appropriate in Persian RTL UI.
4. Preserve chronology clustering, event ordering and canonical-display timestamp rules exactly as implemented by the backend.
5. Preserve `rebuildClaimChronology` and `resolveEvidenceConflict` endpoints, HTTP methods, payload schemas and stored enum values.
6. Locale switching or navigation must not trigger chronology rebuilds or conflict-resolution mutations.
7. Evidence conflicts remain review flags only. Localization must not imply that the system has determined which source is factually correct.
8. Human-authored resolution notes remain source text and may naturally be entered in any language by the operator; the system does not translate or reinterpret them.

## Consequences
- English and Persian operators see equivalent chronology controls and safeguards.
- Source/evidence lineage remains unchanged and audit-safe.
- RTL presentation is improved without changing authoritative claim data, ClaimFacts, AI governance, coverage, liability, causation, recoverability, reserves, settlement/payment or legal rights.
- Browser E2E must verify bilingual presentation and absence of locale-caused chronology mutations.

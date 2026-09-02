# ADR-087 — Localize review-support surfaces without changing decision authority

**Status:** Accepted  
**Date:** 2026-09-02  
**Phase:** 12K  
**Parent:** #135  
**Increment:** #145

## Context
Technical Review, Financial Review, Severity & Reserve Support, and Recovery & Time-bar Intelligence are operator-facing surfaces that combine source-linked evidence, deterministic review support and explicit human decisions. Persian localization must make these workflows usable in RTL without translating or mutating authoritative/source content or changing any decision boundary.

## Decision
1. Locale is presentation-only. API routes, methods, payloads, stored enums, calculations, hashes and workflow semantics remain language-neutral.
2. UI labels, guidance, controls, status/severity/urgency presentation and empty/loading/error copy may be localized.
3. Source evidence, supplier/quotation content, technical findings, rule output, candidate implications, rationale, missing-prerequisite text and existing human-authored notes are not automatically translated or rewritten.
4. Claim references, dates, currencies, monetary values, engineering values, rule/source identifiers and hashes receive controlled LTR presentation inside Persian RTL UI.
5. Financial localization performs no FX conversion and does not alter cost-status values or financial mutation payloads.
6. Severity & Reserve Support remains review support only. Immutable evaluations and append-only human dispositions are preserved; localization cannot create or change authoritative reserve state or `ReserveHistory`.
7. Recovery & Time-bar remains review support only. Candidate dates are explicitly non-authoritative and require human/legal verification; localization cannot convert a candidate date into an authoritative deadline.
8. Locale switching must not trigger build, refresh, resolve, status-update, reserve, recovery, time-bar, task-conversion or decision mutations.

## Verification
- Frontend typecheck/build must pass.
- Existing backend, migration, dependency-lock and Compose validation must remain green.
- Focused Browser E2E switches EN/FA across all four review surfaces and fails if any tracked non-GET mutation occurs as a consequence of localization/navigation.
- Exact-head Continuous Integration and Supply Chain Security must both be green before integration.

## Consequences
The operator can work in Persian or English while the same underlying claim state, reviewed evidence, deterministic calculations, human authority and audit semantics are preserved byte-for-byte at the API/storage boundary.

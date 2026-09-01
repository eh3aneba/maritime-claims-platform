# ADR-083 — Bilingual operator UI and presentation-only locale state

**Status:** Proposed in Phase 12K

## Decision
Use an application-owned typed English/Persian translation catalog and a single client locale provider for the operator UI. Persist the first-increment locale preference in browser localStorage rather than adding a database field. Apply `lang` and `dir` dynamically at the document root.

## Why
The platform now has enough stable operational surfaces to make localization architecture worthwhile. A lightweight in-repo catalog avoids a dependency and keeps compile-time control over English/Persian key parity. Client persistence avoids schema churn while user-profile preference storage is still unnecessary for the MVP.

## Safety boundary
Locale is not domain state. Switching locale must not alter API payload semantics, source evidence, claim facts, AI authorization/governance, calculations, legal-date authority, reserve/settlement/payment state or workflow identifiers.

Candidate time-bar dates remain explicitly candidate/non-authoritative in both languages. Locale must never upgrade a candidate date into a legal deadline.

## Directionality
Persian sets `dir=rtl` and English sets `dir=ltr`. Direction-sensitive shell layout is mirrored. Technical identifiers are isolated with local `dir=ltr` boundaries.

## Consequences
- English remains the no-preference default.
- Preference is browser-local in the first increment and does not roam across devices.
- A future user-profile locale field may replace localStorage without changing translation keys or page contracts.
- Source-content translation remains out of scope and requires a separate governance decision.

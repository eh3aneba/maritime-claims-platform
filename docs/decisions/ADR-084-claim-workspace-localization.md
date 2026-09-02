# ADR-084 — Claim intake and workspace localization boundary

**Status:** Proposed in Phase 12K

## Decision
Localize Claim Intake and the core Claim Overview/Workspace as presentation-only surfaces. The UI may translate labels, help text, status/priority presentation and navigation, but request payload semantics, ClaimFacts, source evidence, audit reasons, workflow enums and reserve authority remain locale-neutral.

## Intake rules
- OCR/extracted candidates remain proposals until explicit human approval.
- The pre-existing default review-note text remains locale-neutral so approval metadata does not silently change merely because the operator switches UI language.
- Claim type/subtype, priority enum and document classification values sent to the API remain unchanged.
- IMO, currency, dates and other technical inputs use local LTR boundaries in Persian.

## Claim workspace rules
- Status advancement uses the same locale-neutral audit reason used before localization.
- Reserve changes remain explicit human actions and use the existing API; localization does not calculate or recommend a reserve.
- Claim references, IMO values, external references, hashes, currency and monetary source values remain directionally controlled.
- Approved Claim Fact values are never translated automatically.

## Deferred evidence module
The embedded Evidence & Documents module is intentionally not modified in this increment. Its malware scanning, quarantine, version replacement, download, intelligence queueing and evidence-security controls require dedicated localization coverage in the next tranche.

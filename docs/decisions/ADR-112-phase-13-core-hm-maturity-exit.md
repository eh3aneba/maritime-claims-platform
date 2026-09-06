# ADR-112 — Phase 13 core H&M maturity exit and operator acceptance

## Status
Accepted as the Phase 13.9C exit design. The implementation is not part of `main` until its pull request passes the exact-head verification gate and receives fresh explicit merge authorization.

## Context
Issue #154 set the Phase 13 direction: mature the existing H&M claims workflow rather than accumulate additional top-level features. Issue #197 narrowed the final maturity work to Correspondence and Claim Pack after the earlier H&M workstreams had reached their governed review surfaces.

Phase 13.9A established deterministic communication-state identity, append-only human review lineage, stale-state fail-closed behavior and exact approval-bound external-dispatch records. Phase 13.9B added dynamic document-request context binding and a bounded, confidentiality-aware Correspondence projection into immutable Claim Pack schema 1.4.

The remaining gap was operator maturity. An approved but unsent communication could not deliberately return to revision; review lineage was technically available but not usable in the operator UI; stale/retry/recovery states were not sufficiently explained in EN/FA; and the complete Correspondence-to-Claim-Pack path did not yet have one final real MT ORION acceptance journey.

## Decision

### 1. Phase 13.9C adds recovery and operator clarity, not a new communication product
An approved, unsent outbound correspondence may be deliberately reopened for revision through a controlled recovery transition.

The transition:
- requires the exact expected correspondence fingerprint/version;
- applies only to outbound approved correspondence that has not been recorded as sent;
- requires a current human approval;
- returns the item to `draft` without rewriting or deleting review decisions;
- clears only the flat current-approval pointers/content hash;
- does not itself change communication identity because wording has not yet changed;
- remains safely idempotent while that exact approved state is still merely reopened; and
- is audit logged as `REOPEN_APPROVED_CORRESPONDENCE_FOR_REVISION`.

A later material edit uses the existing 13.9A state rules: it advances `state_version` / `state_fingerprint`, makes the earlier review historical, and requires submit plus explicit append-only re-review before dispatch can be recorded.

`Sent Externally` records remain immutable and cannot be reopened.

### 2. The Correspondence Centre exposes current state, review integrity and historical lineage separately
The operator UI presents three distinct concepts:
- current workflow status and exact communication state identity;
- whether the latest human review governs that exact current state/context; and
- append-only historical review lineage with review number, action, note, content/state hashes, prior-review linkage and request-context fingerprint where applicable.

The UI localizes review-state and review-action language in English and Persian while retaining hashes and authored content in their original representation. It distinguishes current, stale, legacy-unbound and not-yet-reviewed states and explains the recovery action required.

For approved correspondence the operator sees two explicit human paths:
- revise before external dispatch; or
- confirm that the exact approved wording was actually sent outside the platform and record that dispatch.

For request-linked correspondence whose request context changed, the operator can deliberately return unchanged wording to human re-review without creating a fake communication edit.

### 3. Locale switching is presentation-only
Switching EN/FA/RTL:
- does not translate, rewrite or persist subject/body/recipient/external-reference content;
- does not create a correspondence mutation;
- does not create a Claim Pack export; and
- does not change immutable export metadata.

Authored communication content remains controlled by the human author/reviewer, not by localization logic.

### 4. The final MT ORION journey proves concurrency recovery and immutable downstream handoff
The Phase 13.9C browser acceptance must exercise one real governed path:

1. create an outbound MT ORION draft in the browser;
2. switch EN/FA/RTL and prove authored content is unchanged and no governed mutation occurs;
3. submit and record an exact first human approval;
4. create a competing server-side revision while the browser still holds the earlier approved state;
5. prove the stale browser action fails closed and the UI reloads current state;
6. deliberately revise the recovered draft and submit it for explicit re-review;
7. append a second human approval linked to the first review hash and exact new state;
8. record an external dispatch bound to that exact final approval, while making clear the platform did not send the message;
9. prove locale switching after dispatch does not mutate the record;
10. generate Claim Pack schema 1.4 from the browser;
11. prove the exported XLSX contains the final governed communication and exact sent-review binding; and
12. prove repeated download returns the same immutable bytes and snapshot/file hashes.

This acceptance complements, rather than replaces, the backend integrity tests and the earlier MT ORION H&M acceptance suites.

## Phase 13 / #154 maturity consolidation audit

| Core H&M area | Domain completeness | Integrity / authority | Operator UX | Verification evidence |
| --- | --- | --- | --- | --- |
| Intake / claim identity | Core H&M claim and vessel context established | Tenant-scoped canonical claim state | Mature workbench/localization | Intake and design-partner browser acceptance |
| Documents / evidence | Upload, classification, requirement/evidence workflow | Source-bound evidence and governed requirement state | Evidence Matrix and bilingual review surfaces | Backend + Evidence Matrix browser maturity |
| Chronology | Event chronology and conflict handling | Source/provenance and stale/conflict handling | EN/FA/RTL conflict/review UX | Chronology localization/conflict browser suites |
| Technical investigation | H&M machinery investigation workflow | Human technical review; no machine causation/fault authority | Operator maturity and real MT ORION technical path | Technical backend/browser real acceptance |
| Financials / reserves | Financial claim workstream available | Human financial authority retained; no automated reserve/payment decision | Existing reviewed financial surfaces | Backend and Claim Pack integration coverage |
| Recovery / Time-Bar | Canonical recovery/time-bar workstream | Append-only human decision/action lineage; no automated recoverability/time-bar legal effect | Recovery review/operator workflow | Recovery decision-lineage + Claim Pack reporting acceptance |
| Initial Assessment | Versioned assessment snapshots | Source fingerprint, stale detection, immutable approved digest | Current/historical EN/FA/RTL UX | Real MT ORION assessment acceptance |
| Correspondence | Draft/review/revise/record-dispatch lifecycle | Exact state/context binding, append-only human review, sent immutability | Current/historical/stale/retry/recovery EN/FA/RTL | 13.9A/B backend tests + 13.9C final acceptance |
| Claim Pack | PDF/XLSX controlled downstream reporting | Immutable canonical snapshot/hash; bounded correspondence; sensitive exclusion | Bilingual review-aid/export UX | Claim Pack backend/rendering + repeated immutable download acceptance |

### Consolidation result
Phase 13.9C deliberately does **not** introduce another top-level H&M domain, mailbox, communication sender, legal-decision engine or reporting authority. The mature operator journey remains centered on the existing claim workspace and canonical domain services.

Historical AI rollout/readiness/operations surfaces remain consolidation/deprecation debt rather than a new source of claims authority. They may be simplified or removed in later product-hardening work, but they do not block the Phase 13 core H&M maturity exit so long as canonical claim, evidence, technical, financial, Recovery/Time-Bar, assessment, correspondence and Claim Pack authority remains in the governed modules above.

## Authority and confidentiality boundary
Phase 13 remains a human claims-work support system. It does not autonomously determine coverage, causation, fault, liability, fraud, recoverability, governing law, time-bar legal effect, reserve adequacy, settlement, payment or claim closure.

Correspondence remains human-authored/reviewed. The platform does not send external communications; `Sent Externally` records only a human-confirmed event that occurred outside the platform.

Claim Pack remains a downstream review/reporting artifact. Privileged/without-prejudice markings remain handling signals only; the platform does not determine privilege or waiver. Phase 13.9B's default pre-snapshot exclusion remains unchanged.

## Residual risks and post-Phase-13 hardening
The Phase 13 exit does not claim that all future production hardening is complete. Residual work may include:
- infrastructure observability, load/performance testing and operational SLOs;
- deployment/environment hardening beyond the existing supply-chain and preflight gates;
- further accessibility/usability polish based on design-partner evidence;
- consolidation or retirement of historical AI rollout/readiness surfaces; and
- any future mailbox/provider integration, which would require a separate authority/security design and is explicitly outside this phase.

These are product/platform hardening items, not missing core H&M claims-domain authority.

## Exit gate
Phase 13.9C is merge-ready only when, on the exact pull-request head:
- backend full suite is green;
- PostgreSQL migration/preflight chain is green;
- frontend typecheck/build is green;
- dependency lock and Docker Compose validation are green;
- the full MT ORION browser journey including this final acceptance is green;
- Supply Chain Security is green;
- there are no unresolved review blockers;
- the branch is not behind `main`; and
- fresh explicit user authorization has been given for the Phase 13.9C PR.

No Phase 13.9C merge is authorized merely by completion of this ADR or by an earlier PR approval.

# ADR-095: Deliberate AI re-review and stale batch protection

## Status
Accepted for Phase 13.2C.

## Context
The AI Review workflow already preserves source-linked proposals, explicit human decisions, canonical ClaimFact provenance and append-only ClaimFact revisions. Exact semantic replay of an individual review is intentionally idempotent, while a materially different later human decision is a valid re-review.

Two maturity gaps remained after Phase 13.2B:

1. an individual reviewed extraction could receive a materially different second decision through the API without a separate signal that the reviewer intended a new decision; and
2. grouped and bulk review validated `pending` before acquiring the claim/extraction write locks, leaving a stale-state window in which another reviewer could act before the locked re-read.

The operator UI also did not expose a deliberate path for revisiting an already-reviewed field, even though the backend supported meaningful re-review.

## Decision

### Individual review
`ReviewRequest` carries `confirm_re_review`, defaulting to `false`.

The review service keeps exact semantic replay idempotent before evaluating the re-review guard. Therefore an identical retry does not require confirmation and does not append feedback, audit history or ClaimFact versions.

Any materially different decision on an extraction whose current human status is not `pending` requires `confirm_re_review=true`. Without it, the request fails closed with HTTP 409 and no authoritative mutation.

The existing `/ai-review` field-by-field surface exposes a two-step operator flow: the reviewer first enters **Re-review decision**, then chooses the new approve/edit/reject action. Only actions initiated from that explicit state send the confirmation signal. English/Persian locale switching changes presentation only and never constitutes confirmation.

### Group and bulk review
Grouped and bulk operations remain strictly pending-only and do not support re-review.

The service receives an internal `require_pending` precondition for these batch paths. It re-checks the extraction's current status after the claim/extraction lock and locked re-read. If any row is no longer pending, the operation fails as stale and the enclosing transaction rolls back the entire group/bulk mutation.

This locked-state check intentionally runs before individual replay semantics, because a batch selected from a stale queue must refresh rather than silently treating a concurrent decision as an acceptable replay.

## Consequences
- transport/client retries remain safe and idempotent;
- intentional human re-review is explicit and auditable;
- direct API callers cannot accidentally overwrite a prior review with a different decision;
- group/bulk review cannot become an unintended re-review after a concurrency wait;
- stale group/bulk operations remain all-or-nothing;
- ClaimFact provenance, revision history and restoration semantics remain unchanged;
- no new top-level feature, AI stage, claim domain or autonomous authority is introduced.

## Authority boundary
AI output remains advisory until a human acts. This decision does not authorize automatic ClaimFact approval or any automated coverage, liability, causation, recoverability, reserve, settlement, payment, fraud or legal decision. Tenant, evidence, confidentiality and external-AI controls remain server-enforced.

## Verification
Phase 13.2C must retain focused backend coverage for exact replay, denied/confirmed re-review and stale group/bulk rollback, plus browser acceptance coverage for EN/FA deliberate re-review and canonical fact restoration. Exact-head CI and Supply Chain Security must be green before merge.

Refs #167
Refs #163
Refs #154

# ADR-110 — Correspondence review integrity and exact dispatch binding

## Status
Accepted for Phase 13.9A.

## Context
The Correspondence Centre already required human review before outbound wording could be recorded as sent externally, and approved wording carried a deterministic content hash. The review metadata itself, however, lived on the mutable correspondence row. A later rejected-state edit could replace the flat review fields, stale browser sessions had no optimistic state token, and an external-dispatch record was bound to content hash but not to an immutable human-review decision.

These gaps matter because correspondence can be legally and commercially sensitive even though the platform does not determine legal privilege, coverage, liability, settlement or any other substantive claim outcome.

## Decision

### 1. Material correspondence state has deterministic identity
Each correspondence row carries:
- `state_fingerprint`
- `state_version`

The fingerprint covers the material communication state a human reviews:
- direction;
- kind;
- sensitivity marking;
- sender and recipient labels;
- subject;
- body;
- linked document-request batch ID; and
- sorted linked requirement IDs.

Workflow status, review metadata, dispatch channel/reference/timestamps and other post-review operational metadata are excluded. They must not change the identity of the wording that was reviewed.

Dynamic requirement status is deliberately excluded from the Phase 13.9A fingerprint. Exact document-request-context evolution is a separate concern for Phase 13.9B so unrelated claim changes do not stale ordinary free-form correspondence.

### 2. Human review lineage is append-only
Approve/reject decisions are stored in `correspondence_review_decisions` rather than relying only on mutable flat fields. Each decision records:
- exact correspondence fingerprint/version;
- review number;
- approve/reject action;
- human note and reviewer;
- approved content hash where applicable;
- previous review hash; and
- current review hash.

The existing flat review fields remain as compatibility/current-state projections. Editing a rejected communication may clear those current projections, but it must never delete the historical review chain.

### 3. Governed writes are optimistic and fail closed
Material edit, submit, review and external-dispatch recording require the fingerprint/version observed by the caller. A mismatch returns HTTP 409 and requires refresh/review of the current state.

Database row locks protect the same transitions from concurrent writers after the optimistic check reaches the service layer.

### 4. Exact retries are idempotent
Safe exact retries do not create new history:
- re-submitting the same state already under review returns the current record;
- replaying the same human review by the same reviewer with the same action/note/state returns the existing decision;
- replaying the same external-dispatch record returns the already-recorded result.

A materially different retry fails clearly or requires deliberate re-review. It must not silently overwrite an earlier human decision or dispatch record.

### 5. Revised reviewed correspondence requires deliberate re-review
A material edit creates a new fingerprint/version and returns the correspondence to draft. Prior human review remains historical and therefore becomes stale relative to the new state. After resubmission, a new approve/reject action requires explicit re-review confirmation before another lineage entry is appended.

### 6. External dispatch is bound to the exact approval
Recording `Sent Externally` requires all of the following to agree:
- current correspondence fingerprint/version;
- latest human review is an approval of that exact state;
- caller-provided expected review hash matches that approval;
- approved content hash matches the current content; and
- the same content hash is stored on the approval lineage entry.

The correspondence stores `sent_review_hash` so the external-dispatch record remains traceable to the exact approval that authorized the wording.

The platform still does **not** send email, letters, portal messages or any other external communication. `Sent Externally` records a dispatch the human user confirms occurred outside the platform.

### 7. Existing rows are migrated conservatively
Migration 0076 computes a real state fingerprint from persisted material correspondence content. Where an existing approved/rejected/sent row has sufficient historical flat review metadata, one lineage entry is backfilled. Sent rows are linked to that backfilled approval hash when available. The migration does not fabricate review details that were never stored.

### 8. Alternate inbound promotion paths use the same identity
Human-approved inbound promotion from Email Ingestion and External Portal must bind the resulting correspondence row to the same initial state identity before database flush. This prevents non-null/state-integrity regressions outside the Correspondence Centre UI.

## Authority and confidentiality boundary
This design strengthens integrity of human-authored and human-reviewed records only. It does not determine whether a communication is legally privileged, whether a `WITHOUT PREJUDICE` marking has legal effect, or any question of coverage, causation, liability, recoverability, governing law, time bar, reserve, settlement, payment or claim closure.

Claim Pack inclusion/exclusion rules, including default exclusion of privileged/without-prejudice material, are explicitly deferred to Phase 13.9B.

## Consequences
- stale browser sessions fail closed instead of overwriting newer communication state;
- human review history survives edits and re-review;
- exact network retries are safe where semantics are identical;
- external dispatch is auditable to an exact approval;
- existing inbound integrations remain compatible with the new non-null state identity; and
- no new external-send or substantive claim-decision authority is introduced.

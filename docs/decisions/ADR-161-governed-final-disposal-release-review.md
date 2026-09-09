# ADR-161: Governed final disposal release review

- Status: Accepted
- Date: 2026-09-09

## Context

Phases 17.2-D through 17.2-G established a non-destructive retention governance chain:

1. four-eyes disposal authorization,
2. immutable execution manifest,
3. independently attested dry-run ceremony,
4. reversible logical quarantine staging.

A live quarantine stage still must not become deletion authority merely because time passed or an upstream reviewer already approved earlier steps. Before any future destructive executor could even be designed, the platform needs a final, independently human-reviewed release record that proves the exact live stage and its preservation lineage still match.

## Decision

Introduce `DisposalReleaseReview` as a tenant/claim/quarantine-stage scoped governance record.

### Minimum quarantine dwell

A release review cannot be requested until the quarantine stage has remained live for at least five minutes. This dwell is evaluated explicitly by a human-initiated request; no timer or background job creates authority when the time elapses.

### Bounded review window

A review is valid for at most five minutes and never beyond the linked quarantine stage expiry. Expiry is fail closed.

### Independent final approval

The final approver must be a different local human Admin from both:

- the release requester, and
- the quarantine stage creator.

All mutations require current tenant MFA. AI, service accounts, external signals, rules, workers, webhooks, and timers cannot request or approve release.

### Fresh preservation revalidation

Request and final approval both revalidate the live quarantine stage. Stage revalidation recursively checks the attested dry-run ceremony, execution manifest, current retention policy, legal holds, pending legal-hold proposals, claim/evidence/storage fingerprints, authorization validity, and all pinned hashes.

Any preservation or lineage drift invalidates the review fail closed.

### Immutable release snapshot

The request pins a canonical snapshot containing only governance-safe metadata:

- tenant/claim/stage/ceremony/manifest/authorization/policy IDs,
- manifest/inventory/authorization/ceremony/plan/attestation/overlay/stage hashes,
- policy lineage,
- document count and total bytes,
- stage creator and bounded timestamps,
- minimum release eligibility timestamp.

It contains no raw storage key, file contents, executable credential, or command payload.

### Approval is evidence, not authority

`status="approved"` means only that an independent human successfully revalidated and approved the exact live governance snapshot. It does **not** create:

- a deletion token,
- a storage credential,
- a worker job,
- a physical quarantine action,
- a database tombstone,
- an object lifecycle rule,
- or any irreversible disposal authority.

Audit metadata explicitly records:

- `execution_authority_created=false`,
- `physical_quarantine_performed=false`,
- `destructive_action_performed=false`.

## Lifecycle

`pending_final_approval | approved | rejected | invalidated | expired | cancelled`

Terminal states cannot be revived. A new review requires a fresh upstream governance chain rather than reusing an old quarantine stage.

## Consequences

The retention chain now has a final non-destructive human release gate with explicit cooling-off and separation of duty. A later phase may consider a separately reviewed execution-capability design, but ADR-161 intentionally grants no such capability.

## Explicit non-goals

- no DELETE endpoint
- no claim/document `deleted_at` mutation
- no object-store move/delete/archive/lifecycle mutation
- no physical quarantine/tombstone
- no destructive worker
- no timer-driven action
- no execution credential/token/job payload
- no irreversible action

## Follow-up

If a later phase introduces any executable disposal capability, it must be a separate architecture decision with fresh preservation revalidation, recovery safeguards, explicit human authority, bounded scope, and a new user-approved PR. An approved `DisposalReleaseReview` alone must never be sufficient to erase data.

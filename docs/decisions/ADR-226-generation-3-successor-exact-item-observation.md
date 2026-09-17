# ADR-226: Generation-3 successor exact-item observation

## Status

Accepted for Phase 17.5-V implementation and exact-head production-gate review.

## Context

Phase U records an immutable generation-3 checkpoint from the exact completed Phase T candidate. The next bounded operation is to inspect only the same provider item's metadata and determine whether it is unchanged, changed, or canonically missing.

Phase S already implements the equivalent operation for a generation-2 checkpoint. Reusing its tables by widening generation constraints would weaken an already-reviewed invariant and make historical generation-2 records dependent on future semantics.

## Decision

Phase V uses a separate execution/receipt model with baseline generation fixed to `3`.

Its lineage is:

`U checkpoint generation 3 → T candidate generation 3 → S changed observation → governed R/Q/P/O lineage`

The baseline metadata projection is the exact completed Phase S `changed` observation that Phase T consumed. U/T content facts are revalidated and reconciled against the S metadata baseline on execute and every later GET/receipt read.

The exact provider item identifier is recovered only from the original governed metadata-listing row. It is never accepted from the caller and is never returned by the V API or audit payload.

## Authority boundary

V may construct the transient provider client and perform exactly one bounded exact-item metadata read using the existing reviewed observation policy/adapter. It may persist the resulting metadata projection hashes and classify the result as `unchanged`, `changed`, or canonical `missing`.

V may not list folders, read file content, access or mutate object storage, restage content, advance a checkpoint, create Evidence or a Document, parse/OCR/index content, mutate a Claim, create subscriptions/cursors, or start recurring/background synchronization.

Only provider `not_found` maps to `missing`. Authentication, authorization, timeout, provider unavailability/rejection, malformed/oversized responses, adapter failures, and item-identity mismatch fail closed.

## Integrity and replay

Every execution stores deterministic scope/request/completion hashes and a two-event append-only receipt chain. GET and receipt reads revalidate U, T, S and their deeper lineage before trusting V facts.

Exact replay with the same request key, actor, reason, and U checkpoint returns the completed execution without a second provider call. Changed replay conflicts.

Any new V authority beyond metadata observation requires a separate phase and review.

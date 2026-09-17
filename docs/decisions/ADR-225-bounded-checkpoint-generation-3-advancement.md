# ADR-225: Bounded checkpoint-generation-3 advancement

## Status

Accepted for Phase 17.5-U implementation and exact-head validation.

## Context

Phase 17.5-R records an immutable generation-2 successor checkpoint from the initial generation-1 checkpoint and the Phase Q generation-2 candidate. Phase 17.5-S observes the same exact provider item against that generation-2 baseline. Phase 17.5-T may consume only an S `changed` result and stage one immutable generation-3 quarantine candidate.

The next required authority increase is to advance the synchronization baseline to generation 3 without rereading the provider or touching object storage.

## Decision

Create a **separate generation-3 checkpoint advancement model** rather than weakening the Phase R table's fixed generation-2 constraints.

The exact lineage is:

`R checkpoint generation 2 → S changed observation → T candidate generation 3 → U checkpoint generation 3`

U consumes one completed integrity-valid T candidate and its exact R predecessor. T is revalidated with storage verification disabled so U remains control-plane-only. R is independently revalidated. The generation-3 checkpoint state is derived only from persisted hashes and bounded content facts.

## Authority boundary

U performs zero provider and zero object-storage I/O. It does not construct provider clients, list or read metadata/content, write/delete provider objects, HEAD/GET/PUT/COPY/DELETE storage objects, migrate storage, parse/OCR/index content, create a `Document`, admit Evidence, mutate Claims, or start recurring/background synchronization.

The only new positive authority is recording one immutable generation-3 checkpoint execution and its append-only requested/completed receipt chain.

## Integrity and replay

- candidate generation is fixed to 3;
- predecessor checkpoint generation is fixed to 2;
- successor checkpoint generation is fixed to 3;
- one T candidate may be consumed once;
- one R predecessor may have at most one U successor;
- exact replay with the same actor/request key/reason is idempotent;
- changed replay and competing advancement conflict;
- all U GET/receipt reads revalidate T, R, U state hashes, receipt chain and safety facts;
- T revalidation uses `verify_storage=False`, so U cannot gain storage-read authority indirectly;
- raw storage keys, provider paths/URLs, content, credentials and tokens are never copied into U API/audit surfaces.

## Consequences

Phase R's generation-2 invariant remains explicit and unchanged. Phase U creates a separately reviewable generation-3 baseline that a later phase may consume for successor-aware exact-item observation. Evidence admission/current `Document` creation remains a separate human-controlled authority boundary, and recurring/background synchronization remains later.

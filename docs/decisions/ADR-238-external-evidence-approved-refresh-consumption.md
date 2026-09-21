# ADR-238: One-time consumption of approved observation refresh authority

## Status
Proposed — Phase 17.5-AH.

## Context
Phase 17.5-AG records an explicit Admin + current-MFA decision over a changed recurring external Evidence observation. An approved changed handoff creates a narrow refresh authorization but intentionally performs no provider or storage I/O.

AH must turn that authorization into one exact-item content refresh without reopening broad discovery authority or mutating canonical Evidence.

## Decision
AH consumes one exact AG refresh authorization into one immutable refresh execution.

- The AG authorization is selected under row lock and cryptographically revalidated.
- Current profile, family binding, Claim and canonical Document authority are revalidated before external I/O.
- The canonical Document must still match the AG authorization snapshot.
- Raw provider-item identity is recovered only from the already-governed family/provider lineage and must hash to the authorization's stable source-item hash.
- No remote listing or folder traversal is allowed.
- Exactly one content read is made against that exact item.
- Returned version token, byte count and MIME class must reconcile to the due-tick observation that produced the AG handoff.
- Verified bytes are written to governed quarantine storage under a deterministic execution key.
- The execution row is one-to-one with the authorization and therefore acts as the durable consumption marker.
- Replays return the same completed execution and do not perform another provider read.
- AH does not create or mutate a canonical Document, admit Evidence, enqueue processing, run AI, mutate Claim facts, or advance a sync checkpoint.

## Concurrency
The exact authorization row is locked `FOR UPDATE` through authority revalidation and the exact-item read. A unique `authorization_id` on the AH execution prevents concurrent durable consumption. The execution UUID and storage key are deterministic from the authorization, keeping recovery anchored to one object key.

## Consequences
Human approval remains the only bridge into content refresh. The refreshed bytes remain quarantined and non-canonical until a separate later admission decision.
# ADR-198: Independent health qualification of active authoritative recovery evidence-storage ownership

- Status: Accepted
- Date: 2026-09-12
- Phase: 17.3-AL

## Context

Phase AK can place the authoritative evidence-storage control plane into a bounded, reversible `recovery_storage` state while preserving the local evidence bytes as the immediate rollback copy. Before any later durable or final authoritative-storage ownership ratification is considered, the active AK window requires an independent health review based on fresh lineage, route and byte-integrity evidence.

## Decision

Introduce Phase AL as an observation-only, four-eyes health qualification for exactly one active Phase AK lease. AL accepts only an AK lease that is still active and unexpired, has exactly one activation receipt and no terminal receipt, and whose dedicated authority route remains exact `recovery_storage` at the activation route version.

AL freshly re-verifies the AK→AJ→AI→AH chain. The shared read path must remain `local_source`, the experimental write route must remain `local_only`, the AH durable write route must remain `recovery_primary`, and both preserved local bytes and recovery bytes must still equal the qualified source SHA-256 and byte length.

A request creates one `pending_second_approval` health artifact. An independent Admin+MFA reviewer must qualify or reject it within a ten-minute review window. The qualifier must be independent from the AL requester, AK activator, AJ requester/approver, and material AI/AH/AG/AF/AE/AD actors.

## Observation is not authority mutation

AL records the truth that the observed AK state is currently recovery-authoritative:

- observed authority kind: `recovery_storage`;
- observed AK ownership transition active: true;
- observed local authoritative: false;
- observed recovery authoritative: true;
- observed authoritative-storage changed: true.

Those observations do not mean AL itself changes ownership. Every AL mutation flag is constrained fail-closed:

- local evidence preserved: true;
- storage write performed: false;
- authority-route mutation performed: false;
- ownership mutation performed: false;
- shared read path switched: false;
- write path switched: false;
- `Document.storage_key` mutated: false;
- S3 PUT/COPY/DELETE: false;
- local overwrite/move/delete: false;
- destructive action performed: false;
- physical disposal authorized: false.

## Failure handling

Recovery-storage unavailability during fresh verification is retryable. It does not create a request artifact when the outage occurs before request creation and does not terminalize a pending artifact when the outage occurs during qualification.

Deterministic AK route drift, AK terminalization or expiry, upstream lineage drift, or byte-integrity drift invalidates the pending AL artifact. Review-window expiry terminalizes it as `expired`. These AL transitions do not mutate the AK lease or route; AK reconciliation remains the authority-control mechanism.

Requested, qualified, rejected, expired and invalidated transitions are recorded as append-only, hash-bound receipts.

## Consequences

A qualified AL artifact is independent evidence that one bounded AK recovery-authoritative window remained healthy at qualification time. It grants no durable or final authoritative-storage ownership, no retention deletion authority, no legal-hold override and no physical disposal authority.

Any later ratification of durable/final authoritative-storage ownership must be a separate governance tranche with fresh merge authorization. Deletion of the preserved local evidence copy remains separately governed and out of scope.

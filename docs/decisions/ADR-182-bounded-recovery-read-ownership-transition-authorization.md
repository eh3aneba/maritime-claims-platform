# ADR-182 — Bounded recovery read-ownership transition authorization

## Status
Accepted for Phase 17.3-U implementation.

## Context
Phase 17.3-T produces immutable operational-health evidence for one exact completed Phase S reauthorized durable recovery-read renewal. A healthy/qualified T record proves that the recovery candidate was repeatedly readable under bounded production routing while local evidence remained intact and authoritative.

That evidence is still not authority to change storage ownership. The next step must preserve the same separation used throughout Phase 17.3: governance authorization is distinct from execution.

## Decision
Introduce a separate `EvidenceRecoveryReadOwnershipTransitionAuthorization` and append-only receipt history.

One authorization consumes exactly one healthy/qualified Phase T record and binds:
- the exact Phase T qualification and qualified receipt;
- the Phase S lease and activation/terminal receipts;
- the Phase R reauthorization and already-proven Q→P→O→N→M lineage;
- source/replica hashes, size and storage-key fingerprints;
- source/candidate authority and configuration fingerprints;
- Phase T operational counters and operational-evidence hash;
- the exact clean `local_source` route version.

Request and second approval both perform fresh Phase T snapshot validation. That transitively performs fresh authoritative-local and recovery-replica integrity verification and requires the shared route to remain clean local with no active J/M/P/S authority.

The flow is `pending_second_approval -> approved|rejected|expired|invalidated`. Review and approved-consumption windows are each bounded to ten minutes. Mutations require current-tenant Admin+MFA. The approver is separated from the requester and material Phase T/S/R/Q/P actors.

## Safety boundary
Approval is governance evidence only. Phase U does not:
- create or switch a read route;
- create durable routing authority;
- switch or duplicate the write path;
- mutate `Document.storage_key`;
- change authoritative storage ownership;
- create execution state for a read-ownership transition;
- overwrite, move or delete authoritative local evidence;
- perform S3 COPY/DELETE/lifecycle mutation;
- enable dual-write or disposal.

Database constraints keep all routing/write/storage/destructive flags false on authorization and receipt records.

## Failure semantics
Integrity or lineage drift fails closed. If drift is discovered during second approval, the pending authorization becomes `invalidated` with a minimized immutable receipt. Temporary object-storage unavailability is retryable and does not terminalize the pending authorization.

## Consequences
A later separately reviewed Phase 17.3-V may consume one exact unexpired approved U authorization to introduce a bounded reversible stronger recovery read-ownership transition. Phase V must define its own rollback semantics and receive fresh explicit merge authorization.

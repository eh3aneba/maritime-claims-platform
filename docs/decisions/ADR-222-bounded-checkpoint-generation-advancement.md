# ADR-222: Bounded checkpoint-generation advancement

- Status: Accepted
- Date: 2026-09-16
- Phase: 17.5-R

## Context

Phase 17.5-O records the first synchronization checkpoint for one exact Phase N staged remote file. Its data model is deliberately constrained to `initial_remote_file_snapshot_v1` and generation `1`. Phase 17.5-P can make one bounded metadata-only observation against that checkpoint, and Phase 17.5-Q can consume a `changed` observation to stage one exact immutable candidate generation `2`.

Phase Q intentionally does not mutate the Phase O checkpoint. The candidate is durable custody, but it is not yet an active checkpoint generation.

Extending the Phase O table to represent later generations would weaken a proven invariant: Phase O is an immutable generation-1 record directly tied to Phase N staging. It would also make future change-detection semantics implicit rather than explicitly reviewed.

## Decision

Introduce a separate immutable successor checkpoint-generation execution for Phase 17.5-R.

A successful R execution is derived only from:

1. one exact, integrity-valid Phase O generation-1 predecessor checkpoint already referenced by the Phase Q lineage; and
2. one exact, completed, integrity-valid Phase Q generation-2 candidate whose result is `staged_candidate_verified`.

The successor checkpoint has:

- kind `remote_file_snapshot_successor_v1`;
- generation `2`;
- a deterministic checkpoint-state hash over the predecessor and candidate lineage;
- deterministic scope, request and completion hashes;
- an append-only `requested → completed` receipt chain.

The predecessor Phase O row is never updated. The Phase Q row and its candidate object are never updated.

## Authority boundary

Phase R is control-plane only. It performs no provider or object-storage operation.

In particular, R does not:

- construct a provider client;
- list provider items;
- read provider metadata or content;
- write, move, rename or delete provider data;
- HEAD, GET, PUT, COPY, migrate or DELETE an object-store object;
- stage another content object;
- mutate the Phase O checkpoint;
- mutate the Phase Q candidate;
- create a `Document`;
- admit Evidence or create Claim Facts;
- parse, OCR, render, index or extract content;
- enqueue document processing;
- mutate a Claim;
- create a subscription, cursor, webhook, polling loop or recurring synchronization job.

The Phase Q integrity helper is invoked with storage verification disabled. The R execution therefore relies on already-persisted, integrity-protected Q custody facts rather than performing a fresh object-store observation.

## Why a separate successor model

A separate model preserves three useful invariants:

1. **Generation-1 immutability.** The Phase O schema continues to mean exactly what it meant when validated: one initial checkpoint from Phase N.
2. **Explicit authority edges.** The transition from candidate custody to checkpoint generation is independently auditable and human-triggered.
3. **Future reviewability.** Making later change detection consume successor checkpoints is a separate capability and can be reviewed without retroactively broadening Phase O.

The persisted lineage is explicit:

`O generation 1 → P changed observation → Q candidate generation 2 → R checkpoint generation 2`.

## Replay and concurrency

One exact Phase Q candidate may be consumed at most once. One Phase O generation-1 predecessor may have at most one generation-2 successor in Phase R.

An exact replay by the same actor with the same request key and reason returns the same R execution. A changed replay, a second consumption of the same Q candidate, or a competing successor for the same predecessor fails closed.

The candidate and predecessor are locked while the request anchor is established. Database unique constraints provide a second enforcement layer.

## Integrity and disclosure

R persists only bounded lineage and safe custody facts. It carries the Q storage-object-key hash but never the raw storage key, provider URL, content bytes or credentials.

Every R read revalidates:

- the Phase Q lineage and completion facts;
- the Phase O predecessor integrity;
- the persisted R predecessor/candidate projection;
- the successor checkpoint state hash;
- the request/completion hashes;
- the receipt chain;
- the safety boundary.

Upstream tampering or profile/credential invalidation causes later reads to fail closed.

## Consequences

Phase R creates a durable generation-2 successor checkpoint record, but it does **not** make that record usable by Phase P change detection. Successor-aware exact-item observation requires a later separately reviewed phase.

Likewise, checkpoint advancement does not imply Evidence authority. Human-controlled Evidence admission and the current claim-scoped `Document` creation semantics remain a separate later authority boundary.

Recurring/background synchronization remains out of scope.

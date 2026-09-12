# ADR-200: Durable authoritative recovery evidence-storage ownership ratification execution

- Status: Accepted
- Date: 2026-09-12
- Phase: 17.3-AN

## Context

Phase AK can hold recovery storage as authoritative evidence storage only inside a bounded, reversible ownership window. Phase AL independently qualifies that exact active window, and Phase AM can authorize one short-lived, single-use durable ratification execution. None of those phases makes the bounded authority durable.

Durable authority must be created by a separate execution that is auditable, actor-separated and fail-closed while preserving the local evidence copy and all retention/legal-hold boundaries.

## Decision

Introduce Phase AN as the execution that consumes exactly one approved and unexpired Phase AM authorization and ratifies the current healthy bounded recovery-storage authority into durable recovery-storage authority.

AN requires fresh verification of the full AM→AL→AK→AJ→AI→AH lineage, exact route binding, fresh local/recovery byte integrity and unchanged shared read, experimental write and durable write routes. The executor must be an independent Admin+MFA actor and must be separated from material upstream governance and execution actors.

## Bounded authority becomes durable authority

Before ratification, the authoritative-storage route is:

- authority kind: `recovery_storage`;
- authority tenure: `bounded_recovery`;
- bound to the active Phase AK lease;
- subject to the Phase AK expiry/reconciliation window.

AN increments the authoritative-storage route version exactly once and changes only the authority-tenure control plane:

- authority kind remains `recovery_storage`;
- authority tenure becomes `durable_recovery`;
- the active bounded AK lease pointer is cleared;
- the route binds to the immutable Phase AN ratification artifact;
- the Phase AK lease terminalizes as `ratified`;
- the ratified AK lease no longer participates in automatic bounded-window expiry or rollback reconciliation.

The durable ratification has no automatic expiry. Any future failback, de-ratification or ownership reversion must be separately governed rather than inferred from the old AK lease lifetime.

## Control-plane mutation is not evidence-byte mutation

AN intentionally performs an authority-route and ownership-tenure mutation. Those facts are explicitly recorded:

- route mutation performed: true;
- ownership mutation performed: true;
- durable authority created: true.

AN does not move, replace or delete evidence bytes:

- local evidence preserved: true;
- storage write performed: false;
- shared read path switched: false;
- experimental/durable write path switched: false;
- `Document.storage_key` mutated: false;
- S3 PUT/COPY/DELETE: false;
- local overwrite/move/delete: false;
- destructive action performed: false;
- physical disposal authorized: false.

The preserved local evidence remains available as failback/rollback evidence even though it is no longer the authoritative storage source.

## Replay and failure handling

Exactly one AN ratification may consume an AM authorization. Exact replay with the same executor and reason is idempotent only while the durable route remains bound to the same ratification and route version. Changed replay conflicts.

Recovery-storage unavailability before mutation is retryable and does not consume the AM authorization. Deterministic authorization, lineage, route or byte-integrity drift fails closed before any ratification mutation.

The ratification and its `ratified` receipt are immutable and hash-bound.

## Consequences

Phase AN creates durable authoritative recovery-storage ownership while preserving all evidence bytes and disposal controls.

Phase 17.3-AO should independently qualify the health of the durable authoritative-storage state before storage 17.3 is considered complete.

Deletion of the preserved local evidence copy, retention deletion, legal-hold override and physical disposal remain separate control planes and are out of scope.

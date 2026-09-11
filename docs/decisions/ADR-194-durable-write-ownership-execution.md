# ADR-194: Reversible durable recovery write-ownership execution

## Status
Accepted for Phase 17.3-AH.

## Context
Phase AG creates a short-lived, independently approved governance authorization for one later durable recovery write-ownership execution. It deliberately creates no route lease and leaves both the shared read route and the bounded recovery-write experiment route at exact local authority.

The existing routable dual-write canary route is intentionally a control plane for bounded experiments. Its safety constraints prohibit durable write authority. Reusing that route for a persistent ownership transition would blur the boundary between an experiment and durable routing and would make rollback and later qualification harder to reason about.

## Decision
Phase AH consumes exactly one approved, healthy, unexpired Phase AG authorization and creates one reversible durable recovery write-ownership lease on a separate durable write-routing control plane.

Before activation Phase AH must freshly re-verify the exact Phase AF lineage through Phase AG. The evidence must still show:

- authoritative local evidence matching the approved source hash, byte length and local storage-key fingerprint;
- the recovery replica matching the same source bytes and recovery-storage identity;
- the shared read route at exact `local_source`, with no active recovery-read lease;
- the bounded experiment write route at exact `local_only`, with no active canary or Phase AE lease;
- no authoritative evidence-storage ownership transfer or destructive action.

A separate `EvidenceRecoveryDurableWriteOwnershipRoute` is used for the durable control plane. It has only two modes: `local_only` and `recovery_primary`. Activation creates one `EvidenceRecoveryDurableWriteOwnershipLease`, binds the route to that lease and transitions the durable route from `local_only` to `recovery_primary`.

Unlike the bounded Phase AE transition, an active Phase AH lease has no automatic expiry. It remains active until explicit rollback or a fail-closed reconciliation invalidation. The Phase AG authorization can be consumed only once. Exact activation replay by the same actor with the same reason is idempotent; a changed actor or reason conflicts.

The activator must be independent from the Phase AG requester/approver, Phase AF requester/qualifier, Phase AE activator, Phase AD requester/approver and the preserved AC/AB/AA/Z/Y/X governance actors.

Rollback is permitted only when the durable route is still exactly bound to the active lease. It restores `local_only`, clears the lease pointer, advances the durable route version and writes an append-only receipt. Unsafe route drift is not silently overwritten.

## Safety boundary
Phase AH changes durable write-routing authority only. The transition itself does not:

- perform S3 PUT/COPY/DELETE;
- overwrite, move or delete local evidence;
- switch the shared read route;
- mutate `Document.storage_key`;
- transfer authoritative evidence-storage ownership;
- authorize evidence disposal or physical deletion.

Local evidence remains authoritative and remains the rollback source throughout Phase AH. `durable_write_authority_created=true` therefore means durable recovery write-routing authority exists; it does not mean evidence-storage ownership has transferred.

## Consequences
Phase AH establishes the first persistent recovery-primary write-routing authority while preserving local evidence and a direct rollback path. Because this is stronger than Phase AE, it must be followed by an independent health-qualification tranche before any authoritative storage-ownership transition is considered.

A later phase may qualify the health of the active durable write route. Authoritative evidence-storage ownership transfer and physical disposal remain separate future decisions and require fresh production merge authorization.

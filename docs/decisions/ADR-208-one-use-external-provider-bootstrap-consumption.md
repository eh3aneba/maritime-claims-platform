# ADR-208: Consume bounded external provider bootstrap authority exactly once

## Status
Accepted for Phase 17.5-D implementation.

## Context
Phase 17.5-C authorizes exactly one future provider-connection bootstrap attempt for one active governed source profile and one exact completed discovery lineage. It deliberately performs no credential or provider action and leaves the approved authorization live for at most ten minutes.

The next step must prove that this authority can be consumed exactly once before any credential custody, OAuth exchange or production provider client is introduced.

## Decision
Phase 17.5-D introduces a tenant-scoped immutable bootstrap execution artifact. One valid, unexpired Phase 17.5-C authorization may produce one execution record only.

Execution requires:
- the exact tenant/profile/discovery lineage already bound by Phase 17.5-C;
- an authorization still in `authorized` state with `live_connection_authorized=true`;
- Admin + MFA execution actor;
- an idempotency request key and stated reason; and
- successful immediate revalidation of the Phase 17.5-C authorization and upstream lineage.

The execution stores deterministic SHA-256 scope, request and completion hashes plus an append-only two-receipt chain: `requested → completed`.

### Authorization consumption
Phase 17.5-D does not add a new status to the Phase 17.5-C schema. On successful consumption, the existing Phase 17.5-C authorization is terminalized through its existing fail-closed `expired` state with a deterministic terminal reason containing the exact Phase 17.5-D execution ID. `live_connection_authorized` is cleared immediately.

The Phase 17.5-D execution row has a unique constraint on `authorization_id`, so no second execution can consume the same authority. Exact replay of the same execution facts returns the same immutable execution artifact; changed replay conflicts.

The authorization terminalization and execution artifact/receipts are committed in one database transaction. Any integrity failure can roll the entire operation back rather than leave half-consumed authority.

### Integrity
The execution binds:
- organization/profile/provider identity;
- profile hash;
- discovery run ID, scope hash, manifest hash and run hash;
- authorization ID, authorization scope hash and authorization hash;
- request key, actor, reason and timestamp;
- Phase 17.5-C terminal hash created by consumption; and
- completion timestamp and completion hash.

Read/replay recomputes execution hashes, validates the complete receipt chain, and revalidates the terminalized Phase 17.5-C artifact. The Phase 17.5-C terminal reason must point back to the exact Phase 17.5-D execution ID.

## Safety boundary
Phase 17.5-D is authority-consumption custody only. It introduces no provider adapter, SDK, credential vault reference, OAuth authorization code, access token, refresh token, client secret or private key.

The following are database-constrained false for executions and receipts:
- credential storage;
- credential-reference storage;
- OAuth/token exchange;
- provider network traffic;
- remote list/read/write/delete;
- subscription creation;
- synchronization execution;
- Evidence admission;
- Document creation; and
- claim mutation.

Only `authorization_consumed=true` may become true after successful completion.

## Consequences
The platform now has an auditable one-use bridge from four-eyes connection authorization to a future credential/provider executor, without yet possessing any credential or network authority. A later separately reviewed tranche may define credential-reference custody and a production provider executor, but it must consume the already-established Phase 17.5 lineage rather than bypass it.

## Verification
Release requires full-chain tests covering successful one-use consumption and exact replay, changed replay conflict, expiry, source disable, tenant isolation, receipt tamper rejection, authorization live-authority removal, and zero provider/evidence/document/claim execution.

References: #408, #406, ADR-205, ADR-206, ADR-207.

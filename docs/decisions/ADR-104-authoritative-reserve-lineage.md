# ADR-104: Authoritative reserve lineage remains human-controlled

- Status: Accepted for Phase 13.6C
- Date: 2026-09-05
- References: #185, #154, PR #188

## Context

MCRI already had one authoritative reserve write path: `POST /claims/{claim_id}/reserve`, which updated `Claim.current_reserve` and appended `ReserveHistory`. Separately, Severity & Reserve Support produces deterministic reserve-range review support, and Adjustment Statements provide human-reviewed financial treatment. Neither advisory support nor Adjustment is itself authority to change the claim reserve.

Before Phase 13.6C, authoritative reserve history did not bind a write to an exact prior reserve state, did not provide idempotency, did not preserve source provenance, and did not form an append-only cryptographic lineage. Creating a second reserve table or an automated "set reserve from support" action would introduce conflicting authority and unsafe automation.

## Decision

### 1. `ReserveHistory` remains the sole authoritative reserve lineage

No parallel reserve authority is introduced. Every new authoritative reserve change appends one `ReserveHistory` row and updates `Claim.current_reserve` in the same controlled write transaction.

New Phase 13.6C rows carry:

- claim-local `sequence` / reserve version;
- `idempotency_key` and stable human-request hash;
- optional controlled source kind and exact source reference;
- immutable source-state hash and source snapshot;
- `previous_reserve_hash` and current `reserve_hash`.

Historical rows that predate this contract remain `legacy_unbound` with nullable lineage fields. Migrations do not invent missing evidence, idempotency tokens, historical hashes or source provenance.

### 2. Reserve amount is always an explicit human input

The authoritative amount is supplied only by an authorized Claims Manager or Admin. MCRI does not copy, infer, midpoint, round, optimize or otherwise derive the reserve amount from:

- Severity & Reserve Support candidate ranges;
- Adjustment totals;
- invoices, quotations or estimates;
- AI outputs or rule-engine results.

Source-linked values may be displayed and snapshotted as decision context only.

### 3. Optimistic concurrency and idempotency are mandatory

A new reserve write must include the exact current reserve version and hash returned by the reserve-history read contract. A stale write is rejected and never replayed automatically.

An idempotency key has claim scope:

- exact same human request -> safe replay, no new history row;
- same key with different semantic request -> conflict;
- a new deliberate reserve decision -> new key and current version/hash.

Exact replay remains possible even when the original upstream evidence later becomes historical.

### 4. Optional provenance has three controlled modes

#### Manual

No upstream financial source is selected. The source snapshot explicitly records that the amount was human-entered and not inferred.

#### Reserve Support

A Severity/Reserve Support snapshot may be referenced only if read-only validation confirms that the selected snapshot still matches the current reserve-evaluation inputs. The reserve write transaction must not silently rebuild or replace advisory Support as a side effect.

If the selected Support snapshot is stale, the reserve write is rejected. Refreshing Support is a separate explicit human/operator action; after refresh, the operator reviews the new advisory snapshot and may deliberately submit a new authoritative reserve request. The support range remains advisory, and the human-entered reserve may differ from the lower bound, upper bound or any midpoint.

#### Adjustment

An Adjustment may be referenced only when it:

- belongs to the same tenant and claim;
- is approved;
- is still current against its Financial Review source state;
- uses the claim reserve currency;
- has an immutable approved content hash.

A stale Adjustment must be explicitly rebased and re-reviewed before it can be provenance for a later reserve change.

### 5. Evidence evolution never rewrites reserve history

A historical reserve row records the authoritative reserve decision made at that point in time. Later evidence evolution may make its source snapshot historical context, but it does not make the reserve-history row invalid and never rewrites or reverts it.

If current evidence supports a different reserve, an authorized human records a new reserve version. The new row links to the prior reserve hash.

### 6. Advisory and authoritative domains remain separate

Severity & Reserve Support remains non-authoritative and does not write `ReserveHistory`. Adjustment remains a separate financial-review authority and does not write reserve. Settlement and Payment authorities remain independent.

Phase 13.6C therefore adds lineage, provenance and operator safety without expanding automated decision authority.

## Failure and recovery contract

- stale reserve version/hash -> HTTP conflict; reload current history and deliberately resubmit;
- duplicate idempotency key with changed request -> HTTP conflict;
- stale Reserve Support -> reserve write is rejected without creating a replacement Support snapshot; explicitly refresh Support, review the new snapshot, then deliberately resubmit if appropriate;
- stale/unapproved Adjustment -> rebase/re-review Adjustment before reuse;
- cross-claim or cross-tenant source -> rejected;
- unsupported or mismatched source currency -> rejected;
- upstream source unavailable -> no automatic fallback to another source;
- evidence changes after a successful reserve write -> historical reserve remains immutable; only a new human write can change current reserve.

## Consequences

This design makes reserve changes auditable and concurrency-safe while preserving the existing product authority model. It deliberately prefers a visible human recovery step over silent automation when source state or reserve state changes.

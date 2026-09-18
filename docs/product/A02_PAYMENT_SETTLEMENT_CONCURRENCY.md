# A02 — PostgreSQL payment settlement concurrency

## Purpose

A01 protects the accepted-settlement cap during payment create, resubmit and approval. A02 proves that the invariant remains correct when separate PostgreSQL transactions act at the same time.

## Lock order

Every mutable payment transition uses the same durable ordering:

1. lock the accepted `SettlementProposal` row;
2. lock and refresh the exact `PaymentAuthorization` row when it already exists;
3. validate current workflow state and settlement capacity;
4. perform the transition and commit.

The settlement is the cross-payment serialization point. Refreshing the payment while holding the locks prevents a waiter from continuing with stale ORM state loaded before another transaction committed.

## Covered races

- two concurrent USD 700 creates against one USD 1,000 accepted settlement — exactly one may succeed;
- two rejected USD 700 authorizations concurrently attempting to re-enter active capacity — exactly one may succeed;
- two distinct Managers loading the same `under_review` payment before either approves — serialized execution becomes first approval followed by valid second approval;
- the same Manager attempting both approvals concurrently — the second transition is rejected after authoritative refresh.

## Invariants

- cumulative active payment authority never exceeds the accepted settlement;
- payment workflow state is re-read after lock wait, not trusted from stale pre-lock ORM state;
- one Manager cannot satisfy both approval steps;
- rejected/failed transactions do not leave partially promoted state;
- payment execution remains outside the platform.

## CI

`.github/workflows/postgres-payment-settlement-concurrency.yml` applies the full migration chain to PostgreSQL 18.4 and runs the dedicated concurrency regression module.

## Merge boundary

A02 is stacked on A01 while A01 remains unmerged. After A01 is merged, this branch should be rebased/retargeted so the final PR contains only A02-specific changes. No merge occurs without fresh explicit authorization.

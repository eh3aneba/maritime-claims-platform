# A01 — Payment settlement-cap invariant

## Purpose

Close audit finding F01: a rejected payment authorization must not be able to re-enter an active state when other active payment authorizations have consumed the accepted settlement capacity.

## Invariant

For one accepted settlement, the sum of payment authorizations in active statuses must never exceed the accepted settlement amount.

Active statuses remain:

- draft
- under_review
- first_approved
- authorized
- paid_externally

Rejected payment authorizations release capacity. Any later transition from rejected back to under_review must revalidate capacity under the same settlement-row transaction lock. Approval transitions also revalidate the invariant so legacy or pre-fix invalid rows cannot be promoted into stronger financial authority.

## Concurrency boundary

The API acquires a `FOR UPDATE` lock on the accepted settlement before submit or approval capacity validation. Payment creation already uses the same settlement-row lock. The capacity query excludes the current payment and adds its amount exactly once, making the check valid whether the payment is already active or is re-entering from rejected.

## Non-authority

This remains an authorization ledger only. The platform does not initiate bank instructions or move money.

## Acceptance coverage

- the reproduced USD 1,000 settlement / rejected USD 700 A / active USD 700 B scenario rejects resubmission of A;
- A remains rejected and B remains active after the failed transition;
- approval also rejects a simulated legacy/pre-fix overallocated active row;
- existing settlement/payment separation, immutable hashes, tenant scoping and external-paid recording remain unchanged;
- PostgreSQL concurrency coverage remains a separate A02 work item from the audit roadmap.

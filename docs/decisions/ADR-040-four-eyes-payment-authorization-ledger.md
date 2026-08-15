# ADR-040: Four-eyes payment authorization is a ledger, not payment execution

## Status

Accepted

## Decision

Settlement proposals may be created only from approved immutable adjustment statements and must remain in the same currency and at or below the approved adjusted total.

Payment authorization requires an accepted settlement and two approvals from distinct Manager/Admin users. The creator cannot approve. The second approval creates an immutable SHA-256 content snapshot. Cumulative active authorizations cannot exceed the accepted settlement.

The platform records external payment execution only after explicit confirmation with channel, reference and value date. It never creates a bank instruction, contacts a payment provider or moves money.

## Consequences

- Calculation, settlement terms, internal authority and external execution evidence remain distinct.
- One user cannot create and authorize payment alone.
- Approved content is reviewable and tamper-evident.
- Future bank integration requires a separate security, consent, reconciliation and operational-risk decision.

# Controlled Settlement & Payment Ledger

The ledger separates three legally and financially distinct records:

1. An approved adjustment statement is a human-reviewed calculation source.
2. A settlement proposal records written terms and a proposed amount, but does not send or accept an offer.
3. A payment authorization records internal authority, but does not create a bank instruction or move money.

## Settlement control

A proposal must reference an approved adjustment statement and freezes its ID, version, currency, adjusted total and SHA-256 hash. The proposal currency is inherited and its amount cannot exceed that adjusted total. A Manager/Admin other than the creator reviews it. Approved proposal content is hashed and immutable. Acceptance, decline or withdrawal is a separately audited manual record of an external outcome.

## Payment control

A payment authorization can be created only against an accepted settlement. Active authorizations are summed under a row lock and cannot exceed the settlement amount. The creator cannot approve. Two different Manager/Admin users must approve in sequence; the second approval freezes an immutable content hash.

An authorized payment may be marked `paid_externally` only after an explicit confirmation with execution channel, external reference and value date. This records evidence of an action taken outside the platform.

## Explicit exclusions

- no automated coverage, liability, recoverability, fraud or settlement decision
- no settlement communication
- no payment initiation, bank integration or money movement
- no FX conversion
- no automatic reserve mutation

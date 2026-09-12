# ADR-197: Bounded authoritative recovery evidence-storage ownership execution

- Status: Accepted
- Date: 2026-09-12
- Phase: 17.3-AK

## Context

Phase AJ authorizes one future authoritative evidence-storage ownership execution after independent Phase AI health qualification. AJ deliberately creates no ownership state. The next step must prove that authoritative ownership can move toward recovery storage without conflating authority metadata with physical deletion, storage-key mutation, or read/write routing.

## Decision

Introduce Phase AK as a bounded, reversible authoritative-storage ownership control plane. One exact approved and unexpired AJ authorization may create at most one AK lease. Activation performs fresh AJ→AI→AH lineage and byte-integrity verification, then changes a dedicated authority route from `local_evidence` to `recovery_storage`.

The active AK lease is bounded to 72 hours. Explicit rollback or expiry reconciliation restores exact `local_evidence`. Deterministic route, lineage, or byte drift during an active window invalidates the lease and fails closed back to local authority. Recovery-storage unavailability during fresh verification remains retryable and does not silently change authority.

## Authority is not physical storage mutation

AK changes authoritative ownership metadata/control-plane only:

- authoritative authority route changes: yes, while AK is active;
- recovery storage authoritative: yes, while AK is active;
- local evidence bytes preserved: always;
- `Document.storage_key` mutation: false;
- S3 PUT/COPY/DELETE: false;
- local overwrite/move/delete: false;
- shared read-route switch: false;
- AH durable-write-route mutation: false;
- physical disposal authorization: false.

The preserved local copy is the immediate rollback source throughout the AK window. A recovery-authoritative AK state must never be interpreted as permission to delete the local evidence copy.

## Governance and replay

Activation requires Admin+MFA and an actor independent from the AJ requester/approver and material AI/AH/AG/AF/AE/AD actors. One AJ authorization maps to at most one AK lease. Exact same-actor/same-reason activation replay is idempotent; changed replay conflicts.

Append-only receipts bind activation and every terminal transition to the exact authorization, AI health artifact, source hash and authority-route version.

## Failure handling

Before activation, unavailable recovery storage is retryable and creates no AK lease or authority route. Deterministic admission drift fails closed without consuming the authorization.

During an active window, reconciliation verifies the exact authority route and fresh AJ→AI→AH lineage and bytes. Drift terminalizes the AK lease as `invalidated` and restores local authority. Expiry terminalizes as `expired` and restores local authority. Explicit rollback terminalizes as `rolled_back`.

## Consequences

AK is the first tranche where `authoritative_storage_changed` can truthfully be `true`, but only while the bounded AK lease is active. This remains reversible and preservation-first. A later independent health-qualification tranche must evaluate one active AK window before any durable/final authoritative-storage ownership ratification is considered.

Physical disposal, retention deletion, legal-hold override, and deletion of the preserved local evidence copy remain outside this ADR and require separately reviewed governance and execution phases with fresh merge authorization.

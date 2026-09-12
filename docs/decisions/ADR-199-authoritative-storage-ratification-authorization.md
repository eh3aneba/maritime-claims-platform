# ADR-199: Governance authorization for durable authoritative recovery evidence-storage ownership ratification

- Status: Accepted
- Date: 2026-09-12
- Phase: 17.3-AM

## Context

Phase AK can hold a bounded, reversible authoritative-storage route in `recovery_storage`, and Phase AL independently qualifies the health of that exact active window. A qualified AL artifact is evidence only. It must not be interpreted as permission to make recovery storage durable/final authority.

A later ownership ratification needs a separate governance decision with four-eyes approval, fresh evidence verification, short lifetime and single-use semantics. The governance decision must remain distinct from the execution that would actually create durable/final ownership.

## Decision

Introduce Phase AM as a governance-only authorization tranche. AM consumes exactly one qualified Phase AL artifact and can authorize at most one later ratification execution window.

AM admission requires:

- one exact AL artifact in `qualified` state with exactly one qualified receipt;
- the underlying Phase AK lease still active and unexpired;
- the dedicated authority route still exact `recovery_storage` at the AK activation route version;
- fresh AL→AK→AJ→AI→AH lineage verification;
- shared read route still `local_source`;
- experimental write route still `local_only`;
- AH durable write route still `recovery_primary`;
- preserved local bytes and recovery bytes still matching the qualified source hash and byte length;
- local evidence still preserved as the immediate rollback copy.

An Admin+MFA requester creates one `pending_second_approval` authorization per qualified AL artifact. An independent Admin+MFA approver must act within a ten-minute review window. The approver must be independent from the AM requester, AL requester/qualifier, AK activator, AJ requester/approver and material AI/AH/AG/AF/AE/AD actors.

An approved authorization has a ten-minute execution lifetime and `max_execution_windows = 1`.

## Authorization is not ratification execution

AM records a governance decision that one later execution may ratify durable recovery-storage authority. It does not perform that ratification.

The observed state remains:

- current authority kind: `recovery_storage`;
- observed local authoritative: false;
- observed recovery authoritative: true;
- observed authoritative-storage changed: true.

The AM authorization flag means only that governance approval exists for one later execution. Every execution/mutation flag remains fail-closed:

- local evidence preserved: true;
- storage write performed: false;
- authority-route mutation performed: false;
- ownership mutation performed: false;
- shared read path switched: false;
- write path switched: false;
- `Document.storage_key` mutated: false;
- S3 PUT/COPY/DELETE: false;
- local overwrite/move/delete: false;
- destructive action performed: false;
- physical disposal authorized: false.

## Failure handling

Recovery-storage unavailability during fresh verification is retryable and does not create or terminalize authorization state.

Deterministic AL/AK route, lineage or byte-integrity drift invalidates a pending authorization fail-closed. Review-window expiry terminalizes the pending authorization as `expired`. Requested, approved, rejected, expired and invalidated transitions are append-only and hash-bound.

## Consequences

Phase AM creates governance authority only. A separately implemented and reviewed Phase AN execution is required before durable/final authoritative-storage ownership can exist.

Deletion of the preserved local evidence copy, retention deletion, legal-hold override and physical disposal remain separately governed and out of scope.

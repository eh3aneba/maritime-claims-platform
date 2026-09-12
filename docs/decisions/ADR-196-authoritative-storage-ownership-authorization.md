# ADR-196: Authoritative recovery evidence-storage ownership authorization

- Status: Accepted
- Date: 2026-09-12
- Phase: 17.3-AJ

## Context

Phase AI provides independent evidence that the active Phase AH durable recovery write route, its lineage, and both local and recovery bytes remain healthy. That health evidence does not authorize transfer of authoritative evidence-storage ownership. Moving from local authoritative evidence toward recovery-storage authority is a materially stronger governance step and must be separated from execution.

## Decision

Introduce Phase AJ as a governance-only Four-Eyes authorization control plane. AJ consumes one exact qualified Phase AI artifact, re-verifies the active Phase AH durable route and fresh byte integrity, and may approve one short-lived authorization for one later execution window.

AJ records the current authority as `local_evidence` and the proposed target authority as `recovery_storage`. Approval means only that a later, separately defined execution tranche may attempt one bounded ownership transition while the authorization remains valid.

Request and approval are separate Admin+MFA actions. The approver must be independent from the AJ requester and the material AI/AH/AG/AF/AE/AD governance actors. Storage unavailability remains retryable. Deterministic route, lineage, or byte drift invalidates the pending authorization and produces append-only evidence.

## Authorization versus execution

Phase AJ deliberately distinguishes permission from action:

- AJ approval: governance permission for one future execution window
- authoritative storage changed by AJ: false
- route mutation by AJ: false
- `Document.storage_key` mutation by AJ: false
- storage write/delete/move/overwrite by AJ: false
- physical disposal authorization by AJ: false

This prevents an approved authorization record from being misread as evidence that storage ownership already changed.

## Safety boundary

Phase AJ does not:

- mutate the durable recovery write route, shared read route, or experimental write route;
- perform S3 PUT/COPY/DELETE;
- overwrite, move, or delete local evidence;
- mutate `Document.storage_key`;
- transfer authoritative evidence-storage ownership;
- roll back or reactivate Phase AH;
- authorize physical disposal, retention deletion, or legal-hold override.

Local evidence remains authoritative throughout AJ.

## Consequences

An approved AJ authorization is short-lived, single-window governance evidence only. A later authoritative-storage execution requires a separate phase with explicit route/authority semantics, rollback/failure handling, migration/API boundary, full production gates, and fresh merge authorization. Physical disposal remains out of scope even after any future ownership transition.

# ADR-157: Governed disposal authorization queue

## Status
Accepted for Phase 17.2-D.

## Context
Phase 17.2-A established tenant retention policy versions, formal legal holds, and fail-closed disposal eligibility preview. Phase 17.2-B added non-self-authorizing legal-hold proposals, and Phase 17.2-C added signed external preservation-signal intake that can create proposals only.

The platform now needs a controlled bridge between an eligible retention preview and any future destructive disposal executor. A retention timer becoming eligible is not sufficient authority to destroy claims evidence. The decision must remain human, tenant-scoped, independently approved, short-lived, and invalidated by preservation or evidence drift.

## Decision
MCRI will use a `DisposalAuthorization` work item as a **non-destructive authorization boundary**.

1. A local tenant Admin may request authorization only when a fresh disposal preview is fully eligible.
2. The request pins an immutable snapshot containing:
   - retention policy ID, version number and policy hash;
   - claim retention anchor and expiry;
   - evidence retention anchor and expiry;
   - active legal-hold IDs and pending legal-hold proposal IDs, both empty at an eligible request;
   - a canonical claim/evidence state fingerprint;
   - evaluation timestamp and snapshot hash.
3. The requester cannot approve the same work item. A distinct local Admin is required for four-eyes approval.
4. Tenant MFA policy is enforced for request, approval and rejection mutations.
5. Second approval performs a fresh eligibility evaluation and state reconstruction. Any active hold, pending proposal, policy version change, claim change, evidence change, tenant mismatch, or missing claim invalidates the work item fail-closed.
6. The review window is bounded to 24 hours. An approval attempt after expiry records an `expired` terminal state rather than authority.
7. Approved work items remain records only. Phase 17.2-D contains no claim/document/storage mutation and no disposal executor.
8. Admin and Claims Manager roles may read the queue; only local Admin authority may mutate it.
9. Request, approval, rejection, invalidation and expiry transitions are audited. Audit data records hashes and governance metadata rather than claim/evidence payload content.

## Lifecycle

`pending_second_approval` may transition once to one of:

- `approved`
- `rejected`
- `expired`
- `invalidated`

Approval requires a different Admin from `requested_by_id`. Terminal decisions are not reversible in this phase.

## Non-goals

Phase 17.2-D does **not** add:

- physical deletion;
- soft deletion or tombstoning;
- archive movement;
- object-store lifecycle deletion;
- a bulk disposal worker;
- timer-driven execution;
- AI/rule/webhook/service-account approval;
- restore or rollback operations.

Those concerns require a separately reviewed executor design.

## Consequences

The system can now represent a defensible human authorization decision without conflating eligibility with destruction authority. The snapshot and second-pass revalidation make stale approvals fail closed if preservation obligations or evidentiary state change after the request.

A future Phase 17.2-E may introduce a controlled disposal execution manifest that consumes an unexpired approved authorization. Before any destructive executor is permitted, it must independently revalidate legal holds/proposals, policy lineage, evidence inventory, referential integrity, immutable audit manifest requirements, storage behavior, and recovery/rollback policy. Timer expiry alone must never authorize deletion.

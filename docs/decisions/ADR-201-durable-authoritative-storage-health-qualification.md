# ADR-201: Durable authoritative recovery evidence-storage health qualification

- Status: Accepted
- Date: 2026-09-12
- Phase: 17.3-AO

## Context

Phase AN ratifies the bounded Phase AK recovery-storage authority into durable authoritative recovery storage. The AN transition is intentionally durable and no longer governed by the old bounded AK expiry window. Before Enterprise Storage 17.3 can be treated as closed, the platform needs an independent post-ratification health gate that proves the durable control-plane state and source bytes remain exact.

That health gate must not create another ownership transition. It observes and qualifies the durable state only.

## Decision

Introduce Phase AO as a four-eyes health qualification over the exact Phase AN ratification.

AO admits only a ratification that remains:

- `status=ratified`;
- `authority_kind=recovery_storage`;
- `authority_tenure=durable_recovery`;
- `ratification_active=true`;
- `durable_authority_created=true`;
- recovery-authoritative and not local-authoritative;
- bound by the authoritative-storage route to the same immutable Phase AN ratification;
- free of any active bounded AK lease pointer.

AO requires exactly one hash-bound AN `ratified` receipt and re-verifies the ratification lineage through AM, AL, AK, AJ, AI and AH. The AJ→AI→AH verification is performed without requiring the old AJ execution window to remain unexpired: expiry of a governance window after successful durable ratification does not itself invalidate the durable authority. Deterministic lineage, route or byte drift still fails closed.

## Fresh source-byte verification

AO re-runs the lower durable-write health lineage that verifies the preserved local and recovery copies against the source SHA-256 and byte length. The observed local and recovery copies must remain byte-identical to the source qualified by AN.

Recovery-storage unavailability is treated as retryable before AO state mutation. Deterministic mismatch is not treated as an outage and invalidates a pending AO qualification at qualification time.

## Four-eyes separation

AO request and qualification are separate Admin+MFA actions. The qualifier must be independent from:

- the AO requester;
- the AN executor;
- AM requester/approver;
- AL requester/qualifier;
- AK activator;
- AJ requester/approver;
- AI requester/qualifier;
- AH activator;
- material AG, AF, AE and AD actors.

This separation is persisted in the AO artifact and enforced both by service logic and database constraints for the principal durable-storage actors.

## Observation-only safety boundary

AO performs no authority or evidence mutation:

- local evidence preserved: true;
- storage write performed: false;
- route mutation performed: false;
- ownership mutation performed: false;
- read path switched: false;
- write path switched: false;
- `Document.storage_key` mutated: false;
- S3 PUT/COPY/DELETE: false;
- local overwrite/move/delete: false;
- destructive action performed: false;
- physical disposal authorized: false.

The authoritative-storage route remains at the AN post-ratification version throughout a successful AO request and qualification.

## Review semantics

AO creates one qualification artifact per AN ratification with a short review window and append-only hash-bound receipts.

The states are `pending_second_approval`, `qualified`, `rejected`, `expired` and `invalidated`.

Exact request and terminal replays are idempotent only for the same actor/reason pair. A fresh deterministic verification failure terminalizes a pending qualification as `invalidated`. Recovery-storage unavailability remains retryable and leaves the pending state unchanged.

## Phase 17.3 closure boundary

A `qualified` Phase AO artifact is the health gate for closing Enterprise Storage 17.3. It proves that the durable authoritative recovery-storage state created by AN remained exact and healthy at a separately observed point in time.

AO does not authorize deletion of the preserved local evidence copy, retention deletion, legal-hold override or physical disposal. Those remain separate later control planes.

# ADR-124: Provider checkpoints require explicit crash-safe handoff acknowledgement

- **Status:** Accepted
- **Date:** 2026-09-06
- **Phase:** 15.7
- **Parent:** #214

## Context

Graph delta links and Gmail history checkpoints are opaque provider cursors. The application intentionally stores only SHA-256 fingerprints of those cursors while the raw values remain under operator/external-orchestrator custody.

Before this decision, a successful provider execution committed the new checkpoint hash to `EmailProviderAdapter.checkpoint_hash` in the same transaction that staged provider messages, and then returned the raw checkpoint in the HTTP response. Exact idempotent replay returned the already-recorded run but could not reconstruct the raw checkpoint.

That creates a crash boundary: if the database commit succeeds but the process, network or caller fails before the raw response is durably received, the application has already advanced its accepted checkpoint hash while the caller no longer has the raw value required for the next execution.

## Decision

### 1. Provider execution proposes a checkpoint; it does not activate it

A successful Graph/Gmail pull run that produces a next checkpoint:

- stages provider messages under the existing source/replay controls;
- stores only the SHA-256 checkpoint fingerprint on the execution run;
- marks `checkpoint_handoff_status = pending`;
- leaves the adapter's currently acknowledged `checkpoint_hash` unchanged;
- sets no next provider execution schedule while handoff is pending;
- returns the raw proposed checkpoint only in the initial execution response.

The raw checkpoint is never written to the application database, audit log, reconciliation payload or operations telemetry.

Historical runs default to `not_required`; this migration does not reinterpret old successfully committed cursors as pending handoffs.

### 2. Exact execution replay cannot recreate a lost checkpoint

An exact replay of the same provider execution idempotency key returns the existing run and `replayed=true`, but returns no raw checkpoint.

This is deliberate. The application cannot reconstruct a value that it never persisted. The replay clearly retains `checkpoint_handoff_status=pending` so the operator knows an acknowledgement or abandonment decision is still required.

A different new provider execution is rejected while any handoff for that adapter remains pending. This prevents parallel pages or cursor branches from creating ambiguous checkpoint authority.

### 3. Acknowledgement is a separate operator authority

Only a claims manager or administrator may acknowledge a pending checkpoint handoff.

Acknowledgement requires:

- tenant-scoped Graph/Gmail adapter and execution run;
- active provider adapter and active consented connection;
- succeeded run in exactly `pending` handoff state;
- explicit `confirm_ack=true`;
- the exact raw provider checkpoint supplied by the operator;
- SHA-256 of that supplied checkpoint exactly matching the run's stored proposed fingerprint.

On success:

- only the fingerprint is copied to `adapter.checkpoint_hash`;
- the run becomes `acknowledged` with timestamp;
- normal provider scheduling resumes.

The raw acknowledgement checkpoint is used transiently for comparison and is never persisted or audited.

### 4. Lost-response recovery uses explicit abandonment

If the caller lost the raw checkpoint, a manager/admin may explicitly abandon the pending handoff.

Abandonment requires confirmation and a human reason of at least 20 characters. The reason text is intentionally **not persisted** because an operator could otherwise paste a raw checkpoint, mailbox content or secret into an audit field. Audit records only that a reason was supplied.

On abandonment:

- the run becomes `abandoned` with timestamp;
- the adapter's previous acknowledged checkpoint hash remains unchanged;
- an active source becomes due for re-execution from that prior cursor, or from initial bootstrap if there was no prior cursor;
- already staged messages are not deleted.

Re-execution is safe because provider message identity/content replay controls make repeated staging idempotent and fail closed on materially different provider content.

### 5. Reconciliation exposes state, not checkpoint material

Manager reconciliation may expose:

- whether checkpoint handoff is pending;
- pending run id;
- whether acknowledgement is operationally available;
- whether abandonment is available;
- operational state `checkpoint_handoff_pending`.

It must not expose raw checkpoint values, checkpoint fingerprints, credentials, mailbox content or provider response content.

### 6. Gmail resync reset remains a different authority

Gmail stale-history reset is not a substitute for checkpoint custody acknowledgement.

A Gmail checkpoint reset is rejected while a checkpoint handoff is pending. The operator must first acknowledge or abandon the pending handoff. Only then may the separately governed Gmail stale-cursor reset flow be considered if its own resync-required failure conditions exist.

### 7. Source lifecycle does not silently resolve custody

Suspending or revoking a provider source does not automatically acknowledge or discard a pending handoff.

Acknowledgement requires an active source because it advances the provider cursor and schedules future execution. Abandonment may resolve pending custody while the source is inactive, but no new execution is scheduled until the source is active again.

## Consequences

### Positive

- A process/network failure after message staging cannot irreversibly advance the provider cursor.
- Raw checkpoints remain outside the application database.
- Exact replay remains honest about the inability to recreate raw checkpoint material.
- Operators have a deterministic recovery path when checkpoint delivery was lost.
- Graph and Gmail use the same custody model despite different cursor semantics.
- Future schedulers cannot race ahead of an unacknowledged provider cursor.

### Trade-offs

- Every successful pull page requires an additional acknowledgement action before the next page/run.
- An orchestrator must durably retain the returned raw checkpoint before acknowledging it.
- Lost checkpoint responses require abandonment and safe re-execution from the prior acknowledged cursor.

## Non-authority statement

Checkpoint acknowledgement or abandonment grants no provider send/modify/delete authority, no automatic claim association, no automatic Correspondence promotion, no attachment-byte acquisition, no Evidence admission, no OCR/AI processing authority, and no authority over coverage, causation, fault, liability, fraud, recoverability, governing law, legal time-bar effect, reserve, settlement, payment or claim closure.

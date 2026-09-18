# A03 — Document processing stale-lease recovery and fencing

## Problem
A `DocumentProcessingJob` that was claimed by a worker could remain `running` indefinitely after that worker stopped. Normal claims only select `pending` rows and the Retry API previously returned the existing `running` row, so an expired lease was not recoverable.

## Recovery contract
A running job is stale only when `locked_at` is older than `processing_stale_after_seconds`.

- if attempt budget remains, recovery clears the old owner, returns the job to `pending`, preserves the current `attempt_count`, and applies bounded exponential backoff;
- if the final permitted attempt died, recovery makes the job terminal `failed`;
- extraction-document status is returned from `processing` to `uploaded` for a recoverable job, or to `failed` when attempts are exhausted;
- recovery is audited and does not grant extra attempts;
- the worker loop performs stale recovery before claiming new document work;
- the explicit Retry endpoint is also a recovery point for stale extraction jobs.

## Fencing contract
Recovery alone is unsafe if the old process is still alive. Every document-processing flush is therefore bound to the exact durable lease fingerprint `(job_id, attempt_count, locked_by, locked_at)`.

Before a guarded session flushes processing output, it rereads that fingerprint. If recovery or reassignment changed it, `ProcessingLeaseLost` aborts the stale session and its changes are rolled back. The successor lease remains authoritative.

The normal SQLite backend suite covers state recovery. A dedicated PostgreSQL workflow proves that a recovered/reclaimed lease fences a late old-worker flush under PostgreSQL transaction semantics.

## Explicit boundaries
This change does not increase retry budgets, does not make failed jobs silently successful, does not bypass malware/AI authorization controls, and does not make duplicate stale-worker output authoritative. UI presentation of queued/running/stalled/failed states is follow-on A04 work.

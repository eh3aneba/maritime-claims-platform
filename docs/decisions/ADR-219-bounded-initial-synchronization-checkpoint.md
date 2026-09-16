# ADR-219: Bounded initial synchronization checkpoint custody

## Status

Accepted for Phase 17.5-O implementation, subject to exact-head production validation and fresh merge authorization.

## Context

Phase 17.5-N established durable, hash-verified quarantine custody for one exact remote file body. That custody is deliberately not a synchronization state: it says what was staged, but does not create a durable baseline that later change-detection logic may compare against.

Moving directly from staged content to recurring synchronization would combine multiple new authorities at once: checkpoint custody, future provider reads, change detection, scheduling, multi-run state advancement and potentially local Document/Evidence creation. Phase 17.5-O isolates only the first of those authorities.

## Decision

For one exact completed and integrity-valid Phase N execution, Phase O may create one immutable initial synchronization checkpoint.

The checkpoint is derived entirely from already-persisted and integrity-verified Phase N lineage. It records the exact snapshot identity using bounded hashes and metadata:

- organization/profile/provider lineage;
- Phase N staging execution and completion hash;
- Phase M read and Phase L listing/item lineage identifiers;
- content SHA-256, byte count, media class and version-token hash where available;
- sanitized storage backend/purpose and storage-object-key hash;
- checkpoint kind `initial_remote_file_snapshot_v1`;
- checkpoint generation `1`;
- deterministic checkpoint-state, request and completion hashes.

The raw Phase N storage key is not copied into Phase O. Provider URLs, credentials, tokens, raw responses, object-store credentials, signed URLs and file bytes remain excluded.

## No-I/O checkpoint rule

Checkpoint creation and later checkpoint reads revalidate the persisted A→N lineage but call Phase N integrity verification with storage verification disabled. Therefore Phase O performs no provider list/read/write/delete operation and no object-store PUT/HEAD/GET/DELETE operation.

This is intentional: Phase N already owns content custody and its own recovery/integrity rules. Phase O records a control-plane baseline; it does not re-acquire or re-verify the body through external I/O.

## Authority representation

`checkpoint_created=true` is the sole new positive execution fact on completed Phase O records.

The following remain false for the Phase O action:

- provider client construction;
- remote list/read/write/delete;
- storage read/write/delete;
- durable content staging or content storage;
- `sync_executed`;
- subscriptions/background polling;
- Document creation;
- Evidence admission;
- parsing/OCR/extraction;
- claim mutation.

Upstream completion flags identify the already-validated A→N lineage and do not imply that Phase O repeats those actions.

## Replay and integrity

Exactly one checkpoint is permitted per Phase N staging execution. Exact replay returns the same completed checkpoint. Changed replay or second consumption conflicts.

The checkpoint state hash is a canonical digest of the exact Phase N snapshot facts, independent of caller-supplied checkpoint/cursor/version values. Requested and completed receipts form an append-only deterministic hash chain. Every read revalidates the checkpoint, receipt chain and upstream persisted lineage.

## Consequences

Phase O creates a safe immutable baseline for a later, separately reviewed change-detection phase without introducing polling, provider execution or canonical claim-record authority.

A later incremental synchronization phase must define its own provider-read bounds, change semantics, cursor/version progression, scheduling/retry behavior and crash boundaries. Local Document creation and Evidence admission remain independent authority increases and must not be inferred from the existence of a checkpoint.

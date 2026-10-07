# ADR-263: SFTP production restart, replay and recovery acceptance

## Status

Proposed for Phase 17.6-AE-C.

## Context

The governed SFTP stack persists immutable authority/result records across transport, custody, Evidence, recurring observation, refresh, canonical admission and baseline transition.

Production readiness requires proof that process/runtime replacement does not cause the platform to repeat a remote read or canonical mutation merely because an in-memory adapter registry was lost.

AE-C also closes the exact-file replacement window between pre-open metadata and the opened file handle, and measures the governed path before setting regression budgets.

## Decision

Treat immutable persisted execution/result rows as the replay source of truth.

AE-C verifies restart behavior by deliberately clearing provider adapter registrations after successful durable commits and replaying the exact request.

### Content proof

After one verified exact-file content proof:
- clearing the live SFTP read adapter does not prevent exact replay;
- replay returns the existing proof;
- no second remote content read occurs.

### Approved refresh and crash recovery

A brand-new AB refresh attempt uses a dedicated immutable recovery anchor before provider content I/O:

- while holding the exact human refresh authorization, derive the deterministic quarantine key and prove it is unoccupied with a bounded governed-store metadata check;
- persist one integrity-protected `requested` recovery anchor and one requested receipt before any exact-file content read or quarantine write;
- bind the anchor to the exact authorization, changed observation, current canonical Document/version/hash, provider/profile/source lineage, read adapter/policy identity, storage backend/purpose/key hash, actor, normalized reason and request key;
- commit that anchor before provider/storage mutation, then reacquire and revalidate the same authorization/current lineage before continuing;
- if a retry finds a valid object at the anchored deterministic key, verify storage-internal digest/size plus durable changed-observation invariants and complete the existing AB execution with zero second provider content read and zero second storage write;
- if the anchored key remains empty, the same anchored authorization may perform the controlled reread/write;
- an object found before any anchor exists is an unproven collision/orphan and fails closed; it is never adopted or overwritten.

After a completed AB execution:
- provider runtime may be absent/replaced;
- exact replay returns the prior refresh execution;
- no second SFTP content read or quarantine write occurs;
- a response-finalization failure after the completed DB commit replays from the durable completed execution/receipt.

The anchor is a recovery/audit fact only. AC/AD continue to consume the existing completed AB execution/receipt; the anchor never becomes canonical Evidence authority.

### Canonical admission

After one AC admission:
- exact replay returns the same admission execution and Document N+1;
- signature/malware gates are not invoked again;
- no duplicate canonical version is created.

### Baseline transition

After one AD transition:
- exact replay returns the same transition;
- no provider/storage I/O or second transition/receipt is created.

## Opened-file consistency boundary

A production content read must enforce:

`lstat -> open -> handle.stat -> read`

The opened handle metadata must still describe the same regular file observed by the pre-open lstat. Replacement, symlink drift or metadata identity drift is rejected before the first content byte is accepted.

## Production-shaped adapter integration

The AE-A production registration wrappers are exercised against real governed HTTP/service/DB boundaries using a deterministic injected runtime:
- credential qualification through a supported live registration backend;
- transport verification;
- session activation;
- directory listing;
- bounded exact-file content proof.

Direct `LiveSftpRuntime` coverage remains separate and proves the real transport/authentication/list/stat/open/read/cleanup chain with deterministic socket/Paramiko/SFTP doubles.

## Recovery boundaries

AE-C must prove fail-closed/recoverable behavior for:
- failure before the recovery-anchor commit leaves no durable recovery authority;
- recovery-anchor commit followed by failure before provider read can retry under the same anchor;
- quarantine object persistence followed by failure of the final AB execution commit recovers the anchored object without a second provider read/write;
- completed AB/canonical admission commit followed by response-finalization failure replays from durable completion;
- unanchored pre-existing quarantine objects fail closed and are never promoted;
- duplicate/replayed service dispatch;
- stale schedule and stale human authority;
- host-key mismatch, authentication failure, symlink/path escape, opened-file drift, content-size drift and security-gate rejection.

No recovery path may create a second current Document, repeat remote content reads once an anchored quarantine object exists, or implicitly advance the recurring baseline.

SFTP does not provide a transaction/idempotency token coupled to the application database. Therefore AE-C does **not** claim physical exactly-once remote reads across a process death after the remote read but before any durable object exists. In that narrow window, retry may reread under the same durable anchor/authorization. Concurrent consumers remain serialized, and once the anchored object exists restart performs zero second provider read/write.

## Diagnostics and regression budgets

The production-shaped PostgreSQL scenario records privacy-safe aggregate diagnostics only:
- bounded stage labels;
- elapsed milliseconds;
- SQL query counts;
- integrity-verification segment timings;
- operator-read-model timing.

No SQL text, bind parameters, credentials, hostnames, remote paths, raw quarantine keys, claim identifiers, file bodies, tokens or secret references may be retained. Recovery rows/receipts expose only bounded lineage and hash-safe custody facts.

Regression ceilings are calibrated in two steps: measure the clean exact-head baseline first, then commit explicit CI tripwires with documented headroom. They are not production SLOs.

## CI

Restart/replay and production-adapter acceptance run in the scoped PostgreSQL gates and again in Full Backend on the final clean production head. The focused AE-C PostgreSQL crash gate isolates the anchor/commit/recovery state machine; real PostgreSQL concurrency separately proves row serialization/cardinality, while Full Backend retains the full SFTP lineage crash scenarios. AE-C workflow concurrency cancels stale PR-head runs so acceptance is reported only for the latest synchronized head. The diagnostics artifact is uploaded with `always()` and short retention.

## Consequence

A service restart cannot expand SFTP authority or turn an immutable replay into a second remote read/canonical mutation, and a remote file replacement between pre-open stat and opened handle validation cannot be accepted as the originally authorized object.

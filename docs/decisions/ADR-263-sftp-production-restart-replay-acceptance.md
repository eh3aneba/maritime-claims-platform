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

### Approved refresh

After one AB refresh execution:
- provider runtime may be absent/replaced;
- exact replay returns the prior refresh execution;
- no second SFTP content read or quarantine write occurs.

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

AE-C must prove fail-closed behavior for:
- failure before DB commit;
- durable commit followed by response-finalization failure;
- canonical or quarantine storage write followed by DB rollback;
- duplicate/replayed service dispatch;
- stale schedule and stale human authority;
- host-key mismatch, authentication failure, symlink/path escape, opened-file drift, content-size drift and security-gate rejection.

No recovery path may create a second current Document, repeat remote content reads under consumed authority, or implicitly advance the recurring baseline.

## Diagnostics and regression budgets

The production-shaped PostgreSQL scenario records privacy-safe aggregate diagnostics only:
- bounded stage labels;
- elapsed milliseconds;
- SQL query counts;
- integrity-verification segment timings;
- operator-read-model timing.

No SQL text, bind parameters, credentials, hostnames, remote paths, claim identifiers, file bodies, tokens or secret references may be retained.

Regression ceilings are calibrated in two steps: measure the clean exact-head baseline first, then commit explicit CI tripwires with documented headroom. They are not production SLOs.

## CI

Restart/replay and production-adapter acceptance run in the scoped PostgreSQL admission-execution shard and again in Full Backend on the final clean production head. The diagnostics artifact is uploaded with `always()` and short retention.

## Consequence

A service restart cannot expand SFTP authority or turn an immutable replay into a second remote read/canonical mutation, and a remote file replacement between pre-open stat and opened handle validation cannot be accepted as the originally authorized object.

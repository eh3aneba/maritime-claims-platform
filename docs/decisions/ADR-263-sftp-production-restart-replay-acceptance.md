# ADR-263: SFTP production restart, replay and recovery acceptance

## Status

Proposed for Phase 17.6-AE-C.

## Context

The governed SFTP stack persists immutable authority/result records across transport, custody, Evidence, recurring observation, refresh, canonical admission and baseline transition.

Production readiness requires proof that process/runtime replacement does not cause the platform to repeat a remote read or canonical mutation merely because an in-memory adapter registry was lost.

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

## Production-shaped adapter integration

The AE-A production registration wrappers are exercised against real governed HTTP/service/DB boundaries using a deterministic injected runtime:
- transport verification;
- session activation;
- directory listing;
- bounded file-content proof.

This separates two concerns:
- AE-A unit tests validate the Paramiko runtime itself;
- AE-C integration tests validate that production wrappers obey existing authority and persistence contracts.

## Recovery boundaries

AE-A/AE-C coverage requires fail-closed behavior for host-key mismatch, authentication failure, symlink/path escape, content-size drift, signature/malware rejection, stale authority and canonical-write failures.

## CI

Restart/replay and production-adapter acceptance run in the scoped PostgreSQL admission-execution shard, and again in Full Backend on the final clean production head.

## Consequence

A service restart cannot expand SFTP authority or turn an immutable replay into a second remote read/canonical mutation.

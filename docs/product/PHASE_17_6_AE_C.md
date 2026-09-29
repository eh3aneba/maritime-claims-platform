# Phase 17.6-AE-C — Restart, replay and production-shaped SFTP acceptance

AE-C proves that committed SFTP operations remain safe across process/runtime restarts and that the live adapter code satisfies the read-only production contract.

## Restart model

A restart is modeled as loss of in-memory adapter registrations followed by registration of fresh production adapter instances.

Committed immutable executions must replay from durable state and must not contact SFTP again merely to reproduce an already-committed response.

## Proven replay boundaries

### Initial content proof

After one successful exact-file read and committed content proof:
- adapter registry is cleared;
- a fresh production content adapter is registered;
- exact request replay returns the original proof;
- the fresh runtime performs zero remote reads;
- a new request key for the already-proven exact listing entry is rejected before provider I/O.

### Changed refresh

After one approved changed-file reread and verified refresh staging:
- adapter registry is cleared;
- a fresh production content adapter is registered;
- exact execution replay returns the committed refresh;
- no second content read or staging write occurs.

### Post-admission authority

After canonical N+1 admission:
- fresh processing release replay is DB-only;
- recurring baseline transition replay is DB-only;
- neither action contacts SFTP after restart.

## Production-shaped runtime

AE-C executes the actual `LiveSftpRuntime` with deterministic socket/Paramiko test doubles.

The code under test performs:
- SSH client handshake;
- OpenSSH SHA256 host-key capture/verification;
- credential lookup after host-key verification;
- password authentication;
- SFTP subsystem activation;
- directory listing;
- exact lstat metadata;
- lstat-before-read content access;
- immediate socket/transport/SFTP cleanup.

This is distinct from the older deterministic service adapters: the production runtime implementation itself is exercised.

## Security negatives

- pinned host-key mismatch fails before credential resolution;
- symlink content target fails after lstat and before file open/read;
- remote-root path escape is rejected.

## Privacy

AE-B low-cardinality SFTP events and operator serialization tests remain part of the stacked closure.

No test or production event should expose secret values, raw credential material or evidence body content.

## Final closure

After W→AD and AE-A/B/C are clean-rewritten onto merged main, run the complete exact-head production gate matrix and one consolidated SFTP acceptance pass before closing parent #628.

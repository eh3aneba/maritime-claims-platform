# Phase 17.6-AE-C — Production restart/replay and recovery acceptance

AE-C closes the production reliability loop for SFTP after AE-B.

## Restart rule

A process restart clears in-memory provider adapters, not durable authority.

For an exact previously completed request:
- content proof replays without another file read;
- approved refresh replays without another remote read/quarantine write;
- canonical admission replays without another Document version;
- recurring baseline transition replays without another transition.

Replay acceptance must assert persistent row/receipt counts, provider read/stat counters, quarantine writes, security-gate counters and current-version cardinality — not only stable IDs.

## Production-shaped governed scenario

The final AE-C acceptance must exercise one contiguous governed path:

profile → four-eyes credential-reference approval → live credential qualification → host-key verification → session activation → listing → exact metadata/content proof → v1 Evidence → family binding → fresh v1 processing release → recurring schedule → unchanged observation → changed observation → refresh review/approval → one exact reread → AB quarantine → AC N+1 → fresh N+1 processing release → AD baseline transition → next unchanged observation.

Supported secret backends are `azure_key_vault` or `gcp_secret_manager`; test-only historical backends are not acceptable for production-shaped qualification.

## Direct live runtime proof

AE-C separately preserves a deterministic positive `LiveSftpRuntime` chain covering SSH handshake, OpenSSH SHA256 host-key capture, host-key revalidation, credential resolution, authentication, SFTP activation, listing, exact `lstat`, opened-handle validation, content read and cleanup.

Negative guarantees remain fail closed for host-key mismatch, authentication failure, weak negotiated host-key algorithm, symlink/path escape and resource cleanup on success/failure.

## Opened-file drift

Exact content access must enforce:

`lstat → open → handle.stat → read`

If the opened handle no longer matches the pre-open regular-file metadata, the request fails before the first content byte is accepted.

## Due-tick restart replay

After a schedule dispatch is durably consumed, replace/clear the provider metadata adapter and replay the same dispatch. The replay must return the same observation/consumption IDs with no second provider stat/read, no duplicate receipt and no Document or processing-job mutation.

## Crash-window recovery matrix

AE-C explicitly covers:
- failure before DB commit leaves no durable success/authority row;
- committed immutable execution survives response-finalization failure and replays without provider/storage I/O;
- storage write followed by DB rollback cannot produce a current N+1 without execution lineage;
- quarantine/staging rollback cannot create a reusable orphan that bypasses refresh authority;
- competing service executors remain single-consumer;
- stale/replaced schedule and stale human authorization fail before consuming admission/baseline authority.

## Privacy-safe diagnostics

The PostgreSQL production-shaped scenario measures stage duration and SQL query counts with test-only instrumentation. The artifact contains aggregate labels/numbers only and must exclude SQL text, bind values, credentials, usernames, raw hostnames/paths, secret references, claim identifiers, file contents and tokens.

Regression budgets are calibrated after the first exact-head measured baseline; ceilings are CI tripwires rather than production SLOs.

## CI acceptance

Before Ready for Review / merge, the clean AE-C head must pass:
- scoped PostgreSQL admission-execution acceptance;
- Full Backend exact-head validation;
- Supply Chain Security;
- Operational Performance Smoke;
- Production Deployment Policy;
- Continuous Integration;
- browser acceptance where the operator flow is affected.

The diagnostics artifact is uploaded on `always()` with short retention while functional/integrity assertions remain fail closed.

## Merge control

AE-C is built only on merged `main`. No historical stacked AE-C branch is rebased or merged. Fresh explicit user authorization is required before final merge.

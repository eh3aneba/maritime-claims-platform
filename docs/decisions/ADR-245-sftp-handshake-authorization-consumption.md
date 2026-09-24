# ADR-245: Consume one SFTP handshake authorization locally before any network operation

## Status

Accepted for Phase 17.6-E implementation planning.

## Context

Phase 17.6-D creates a short-lived, one-use authorization for one future bounded SFTP handshake attempt. The authorization remains a governance fact only; it performs no DNS, socket, SSH, SFTP or remote-file activity.

A live authorization must not itself be reusable execution authority. The platform needs an explicit atomic consumption boundary before any later network phase.

## Decision

Phase 17.6-E consumes exactly one live Phase 17.6-D authorization into one durable local execution record.

Consumption is local-only. No provider or SFTP network operation occurs.

The execution:
- locks the exact Phase 17.6-D authorization row;
- revalidates the full A→B→C→D lineage;
- requires D to be authorized, unexpired and execution_limit=1;
- creates one execution request;
- immediately terminalizes the D authorization with an execution-specific consumption reason;
- clears `sftp_handshake_authorized`;
- binds the D terminal hash into the E completion;
- marks `handshake_authorization_consumed=true`;
- emits requested/completed hash-chained receipts.

## Concurrency

The authorization row is locked with `FOR UPDATE`.

A second concurrent consumer re-checks after obtaining the lock. At most one execution may consume an authorization.

Exact replay returns the same execution. Materially changed replay conflicts.

## Safety boundary

Phase 17.6-E performs no:
- raw credential resolution or persistence;
- DNS lookup;
- TCP connection;
- SSH transport/key exchange;
- live host-key verification;
- authentication;
- SFTP session creation;
- remote list/stat/read/write/rename/delete;
- checkpoint or staging operation;
- Evidence admission;
- Document creation;
- downstream processing;
- AI execution;
- Claim mutation.

The only positive execution fact is `handshake_authorization_consumed=true`.

## Authorization terminalization

A successfully consumed D authorization is terminalized using the existing D terminal lifecycle with an execution-specific reason:

`Phase 17.6-E handshake execution <execution_id> consumed this bounded SFTP handshake authorization.`

This preserves the D schema and receipt model while proving the live authorization can no longer be reused.

If D is already naturally expired, E records no successful execution.

## Consequences

Approval and execution remain separate.

No future network phase can rely directly on a reusable D authorization; it must rely on one immutable completed E execution.

## Next boundary

Phase 17.6-F may use one completed E execution as prerequisite for the first actual bounded network action: transient SSH transport establishment and pinned host-key verification under strict destination policy.

Directory listing, remote file reads and writes remain excluded.

## Verification

Release requires:
- exact authorized D;
- row-lock double-consumption protection;
- exact replay;
- changed replay conflict;
- tenant isolation;
- expiry rejection;
- upstream and D tamper rejection;
- D live authority cleared on completion;
- D terminal hash bound into E;
- receipt tamper/truncation rejection;
- all secret/network/session/file/Evidence/AI/Claim facts false.

References: Issue #541, Issue #539, ADR-244.

# ADR-244: Authorize one bounded SFTP handshake attempt before any network execution

## Status

Accepted for Phase 17.6-D implementation planning.

## Context

Phase 17.6-A governs the SFTP source profile, including normalized host/port/root/username identity metadata, read-only intent and a pinned host-key fingerprint.

Phase 17.6-B governs a non-secret reference to externally managed SFTP authentication material.

Phase 17.6-C qualifies that exact credential reference and records whether the resolved material class matches the approved authentication kind, while still performing no SSH/SFTP connection or remote-file operation.

The next authority increase must remain small and auditable. A successful credential-health result must not automatically grant network execution.

## Decision

Phase 17.6-D introduces a short-lived, one-use governance authorization for one later bounded SFTP handshake attempt.

The authorization is bound to one exact, integrity-valid Phase 17.6-C qualification with `result_status=qualified` and therefore transitively to the exact Phase 17.6-A profile and Phase 17.6-B credential-reference custody.

## Independent approval

A request requires Admin + MFA.

A different Admin + MFA actor must approve it. Self-approval is rejected.

The review window is fixed at 10 minutes. Once approved, the authorization is valid for 10 minutes and has `execution_limit=1`.

Lifecycle:

- `pending_second_approval`
- `authorized`
- `rejected`
- `expired`

Exact replay is idempotent. Materially changed replay conflicts.

## Integrity lineage

The authorization lineage binds at minimum:

- organization/profile identity;
- exact profile hash;
- exact credential-reference binding ID;
- binding scope/request/approval hashes;
- locator hash;
- authentication kind;
- reference backend;
- exact Phase 17.6-C qualification ID;
- health scope/request/result hashes;
- health result status;
- request facts;
- review TTL policy;
- approval facts;
- authorization TTL policy;
- execution limit;
- terminal facts.

Requested, authorized, rejected and expired receipts form an append-only hash chain.

## Positive authority fact

The only new positive capability fact is `sftp_handshake_authorized=true` while the authorization is in the live `authorized` state.

This means only that a later phase may attempt to consume the authorization. It does not mean any network activity has occurred.

## Safety boundary

Phase 17.6-D performs no:

- credential-byte resolution or persistence;
- DNS lookup;
- TCP socket connection;
- SSH key exchange;
- network host-key verification;
- SFTP authentication;
- SSH/SFTP client or session creation;
- directory listing;
- stat/read/write/rename/delete;
- checkpoint creation;
- remote-content staging;
- Evidence admission;
- Document creation;
- processing enqueue;
- AI execution;
- Claim mutation.

All corresponding DB/service safety facts remain false.

## Consequences

The platform obtains an explicit human-controlled approval boundary immediately before future SFTP connectivity.

A successful 17.6-C qualification cannot silently become network authority.

## Next boundary

Phase 17.6-E should atomically consume exactly one unexpired 17.6-D authorization into a one-use execution record and immediately clear the live authorization fact, still without network I/O.

A later separately reviewed phase may then perform the actual bounded SSH transport and pinned-host-key handshake.

## Verification

Release of 17.6-D requires:

- exact qualified 17.6-C lineage;
- upstream A/B/C integrity revalidation;
- tenant isolation;
- four-eyes approval;
- self-approval rejection;
- exact replay and changed-replay conflict;
- fixed review and authorization TTL enforcement;
- automatic expiry;
- rejection lifecycle;
- receipt-chain integrity;
- tamper/truncation rejection;
- execution_limit=1;
- no secret/network/session/file/Evidence/AI/Claim execution.

References: Issue #539, Issue #537, ADR-243.

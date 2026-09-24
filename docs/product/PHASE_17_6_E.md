# Phase 17.6-E — consume one SFTP handshake authorization locally

## Goal

Spend one Phase 17.6-D handshake authorization exactly once without contacting the SFTP server.

## Plain-language model

17.6-D is a one-use permission slip.

17.6-E punches a hole in that permission slip and records that it has been used.

The system still does not connect to SFTP.

## Preconditions

Execution requires:
- one exact active/integrity-valid A→B→C→D lineage;
- D status `authorized`;
- `sftp_handshake_authorized=true`;
- D authorization not expired;
- `execution_limit=1`;
- Admin + MFA requester.

## Execution semantics

1. find any exact replay;
2. lock the D authorization row;
3. re-check exact replay after the lock;
4. validate D and upstream integrity;
5. reject pending/rejected/expired/tampered authority;
6. create one local E execution request;
7. terminalize D with an E-specific consumption reason;
8. clear D live handshake authority;
9. bind the D terminal hash into E;
10. complete E with `handshake_authorization_consumed=true`;
11. emit requested/completed receipts.

## API shape

Planned endpoints:

- `POST /api/v1/external-document-sources/profiles/{profile_id}/sftp-handshake-authorizations/{authorization_id}/handshake-executions`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/sftp-handshake-executions/{execution_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/sftp-handshake-executions/{execution_id}/receipts`

All require Admin + MFA.

## Safety boundary

E does not:
- resolve credential bytes;
- perform DNS;
- open TCP/SSH/SFTP sockets;
- perform SSH key exchange;
- verify a host key over a live connection;
- authenticate;
- create an SFTP session;
- list/read/write/delete remote files;
- create checkpoints or stage content;
- admit Evidence or create Documents;
- enqueue processing;
- execute AI;
- mutate Claims.

## Acceptance

- exact D authorized state required;
- expiry terminalizes D and refuses consumption;
- one execution per D authorization;
- concurrent double-consumption prevented;
- exact replay idempotent;
- changed replay conflict;
- request-key collision conflict;
- tenant isolation;
- D live authority cleared;
- D terminal hash bound into E completion;
- receipt chain integrity;
- tamper/truncation rejection;
- all execution/network/file/AI/Claim safety facts false.

## Next boundary

17.6-F can introduce a transient SSH transport + pinned-host-key verification operation using one completed E execution, without listing or reading remote files.

See ADR-245 and Issue #541.

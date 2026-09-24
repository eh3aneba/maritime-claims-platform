# Phase 17.6-D — bounded SFTP handshake authorization

## Goal

Authorize one future bounded SFTP connection + pinned-host-key handshake attempt without performing that connection in this phase.

## Why this is separate

Phase 17.6-C proves that the approved credential reference is structurally usable. That proof must not automatically become permission to contact the remote SFTP server.

17.6-D adds a separate human approval boundary.

## Preconditions

A request requires:

- an active, integrity-valid Phase 17.6-A SFTP source profile;
- an active, integrity-valid Phase 17.6-B credential-reference binding;
- an integrity-valid Phase 17.6-C health qualification;
- `result_status=qualified`;
- exact A→B→C hash lineage;
- Admin + MFA requester.

Approval requires a different Admin + MFA actor.

## Lifecycle

- `pending_second_approval -> authorized`
- `pending_second_approval -> rejected`
- `pending_second_approval -> expired`
- `authorized -> expired`

Policy:

- review TTL: 10 minutes;
- approved authorization TTL: 10 minutes;
- execution limit: exactly 1.

## Authorization meaning

While status is `authorized`, the record may expose one governance fact:

- `sftp_handshake_authorized=true`

That fact means only that a later phase may consume the permission.

It does **not** mean an SSH/SFTP connection exists.

## API shape

Planned endpoints:

- `POST /api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-health-qualifications/{qualification_id}/handshake-authorizations`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/sftp-handshake-authorizations/{authorization_id}/approve`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/sftp-handshake-authorizations/{authorization_id}/reject`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/sftp-handshake-authorizations/{authorization_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/sftp-handshake-authorizations/{authorization_id}/receipts`

All endpoints require Admin + MFA.

## Safety boundary

17.6-D does not:

- resolve raw passwords/private keys/passphrases;
- perform DNS or network activity;
- open TCP/SSH/SFTP sockets;
- perform SSH key exchange;
- verify a remote host key over the network;
- authenticate;
- construct or retain an SFTP session;
- list or read remote files;
- write/rename/delete remote files;
- create checkpoints;
- stage content;
- admit Evidence or create Documents;
- enqueue processing;
- execute AI;
- mutate Claims.

## Acceptance

- qualified 17.6-C required;
- unqualified C rejected;
- upstream disable/tamper fails closed;
- tenant isolation;
- independent approval;
- self-approval rejected;
- exact replay idempotent;
- changed replay conflict;
- pending review expiry;
- authorized expiry;
- explicit rejection;
- hash-chain receipt integrity;
- receipt tamper/truncation rejection;
- TTL-policy drift rejection;
- execution_limit fixed to one;
- all execution/network/file/AI/Claim safety facts remain false.

## Next boundary

17.6-E consumes one live authorization into a one-use execution record and clears the live authorization flag, still without contacting the SFTP server.

The actual SSH transport + pinned-host-key handshake remains a later separately reviewed authority increase.

See ADR-244 and Issue #539.

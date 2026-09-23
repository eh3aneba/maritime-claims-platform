# ADR-242: Govern SFTP credential-reference custody before any network authority

## Status

Accepted for Phase 17.6-B implementation.

## Context

Phase 17.6-A introduced governed SFTP source profiles containing only normalized connection identity metadata, a pinned host-key fingerprint and an immutable read-only intent. It intentionally stopped before secret custody, secret resolution, authentication or network I/O.

The existing SharePoint / Google Drive credential-reference custody is downstream of a completed Phase 17.5-D bootstrap execution. SFTP has no equivalent bootstrap execution yet. Reusing that lineage would manufacture an authority transition that has not occurred.

## Decision

Phase 17.6-B introduces a separate, profile-bound SFTP credential-reference custody record.

One active SFTP source profile may bind to at most one credential reference. Replacing the reference therefore requires a newly governed source profile rather than silently rebinding existing authority.

The binding stores only:

- authentication kind metadata: `password` or `private_key`;
- one supported external secret-manager backend;
- a constrained namespace identifier;
- a constrained secret/reference name; and
- an optional constrained version label.

The application does not accept a generic secret URI and does not accept raw password, private-key or passphrase fields.

## Approval and lifecycle

An Admin + MFA requester creates the binding. A different Admin + MFA actor must approve it before it becomes active.

Lifecycle:

- `pending_second_approval -> active`;
- `pending_second_approval -> rejected`; or
- `active -> disabled`.

Every transition emits an append-only hash-chained receipt. Exact replay is idempotent; materially changed replay conflicts.

Pending and active bindings are usable only while the exact bound SFTP profile remains active and integrity-valid. Rejected and disabled bindings remain readable as historical governance records.

## Integrity

The binding lineage includes:

- organization and profile identity;
- `provider_kind = sftp`;
- exact profile hash;
- authentication kind;
- canonical credential-reference locator hash;
- request key and requester facts;
- independent approval facts; and
- terminal rejection/disable facts.

The profile hash already cryptographically binds the normalized SFTP hostname, port, remote root, username, host-key fingerprint and read-only access intent established in Phase 17.6-A.

## Safety boundary

`credential_reference_stored=true` means only that approved non-secret locator metadata exists.

Database constraints and service integrity verification keep all of the following false:

- raw credential custody;
- secret-manager resolution;
- provider network activity;
- authentication attempts;
- SSH/SFTP session creation;
- remote list/read/write/delete;
- Evidence admission;
- Document creation;
- downstream processing;
- AI execution; and
- Claim mutation.

Phase 17.6-B performs no DNS lookup, socket creation, secret retrieval or SFTP protocol operation.

## Consequences

The platform can review and govern where future SFTP authentication material will be resolved without acquiring the material or connectivity authority itself.

A later Phase 17.6-C may add narrowly bounded reference resolvability/health qualification. That phase must remain separately reviewed and must not silently broaden into file listing or content reads.

## Verification

Release requires:

- active SFTP-profile lineage;
- tenant isolation;
- strict input and secret-like value rejection;
- independent approval;
- replay/conflict behavior;
- reject/disable history;
- profile-disable fail-closed behavior;
- receipt-chain tamper detection; and
- proof that no network, secret-resolution, Evidence, Document, processing, AI or Claim authority was exercised.

References: issue #535 and Phase 17.6-A / PR #517.

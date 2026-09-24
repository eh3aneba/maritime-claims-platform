# Phase 17.6-C — SFTP credential-reference health qualification

## Goal

Prove that one approved Phase 17.6-B SFTP credential reference can be resolved and that its material class matches the approved authentication kind, without opening an SSH/SFTP session or remote-file authority.

## Preconditions

A qualification requires:

- one integrity-valid Phase 17.6-A SFTP source profile;
- that profile to remain active;
- one active, integrity-valid Phase 17.6-B SFTP credential-reference binding;
- the exact profile/binding hash lineage;
- an Admin + MFA requester; and
- one registered resolver for the approved secret-manager backend.

## Resolver boundary

The resolver may internally resolve the approved secret-manager reference.

The service receives only:

- `resolved: true/false`;
- `material_kind: password/private_key` when resolution succeeds; and
- one bounded failure code when it does not.

The service never receives raw password/private-key/passphrase contents.

## Outcome

The result is:

- `qualified` when resolution succeeds and `material_kind == authentication_kind`;
- `unqualified` otherwise.

Supported bounded failure classes include:

- `reference_not_found`;
- `reference_unresolved`;
- `permission_denied`;
- `backend_unavailable`;
- `resolver_rejected`;
- `material_missing`;
- `material_invalid`; and
- `authentication_kind_mismatch`.

## One-use semantics

Each SFTP credential-reference binding can produce only one qualification.

Exact replay returns the same row and does not call the resolver again. Changed replay conflicts.

The binding row is locked before qualification so concurrent consumers cannot create duplicate resolution attempts.

## API

- `POST /api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/health-qualifications`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-health-qualifications/{qualification_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-health-qualifications/{qualification_id}/receipts`

All endpoints require Admin + MFA.

## Safety boundary

Phase 17.6-C may resolve only the approved external secret-manager reference.

It does not:

- persist or return secret contents;
- authenticate to SFTP;
- open SSH/SFTP sockets or sessions;
- list/read/write/rename/delete remote files;
- create checkpoints;
- stage content;
- admit Evidence or create Documents;
- enqueue processing;
- execute AI; or
- mutate Claims.

DB constraints keep those capability facts false.

## Acceptance

- tenant isolation;
- active exact Phase 17.6-B binding required;
- exact replay does not repeat resolution;
- changed replay conflicts;
- successful matching material qualifies;
- material-kind mismatch becomes bounded unqualified result;
- unavailable resolver fails before creating authority;
- resolver exceptions become bounded auditable `resolver_rejected`;
- upstream disable/tamper fails closed;
- receipt tamper fails closed;
- no ephemeral material appears in API, DB or audit;
- no SFTP/file/Evidence/processing/AI/Claim authority.

## Next boundary

Phase 17.6-D may introduce bounded SSH/SFTP connection and pinned-host-key handshake authorization. Directory listing and file reads remain separate later boundaries.

See ADR-243 and Issue #537.

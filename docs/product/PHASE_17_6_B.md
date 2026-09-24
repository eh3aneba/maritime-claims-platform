# Phase 17.6-B — Governed non-secret SFTP credential-reference custody

## Goal

Attach one governed reference to externally managed SFTP authentication material to one active Phase 17.6-A SFTP source profile, without resolving secrets or opening any SSH/SFTP connection.

## Admission boundary

A request requires:

- one integrity-valid SFTP external document source profile;
- that profile to be `active`;
- `provider_kind = sftp`;
- an Admin + MFA requester; and
- canonical non-secret credential locator metadata.

A different Admin + MFA actor must approve the request before it becomes active.

Unlike SharePoint / Google Drive credential-reference custody, this phase does not depend on a bootstrap execution because Phase 17.6-A intentionally created no SFTP bootstrap/network authority.

## Canonical reference

The binding stores only:

- `authentication_kind`: `password` or `private_key`;
- `reference_backend`: `aws_secrets_manager`, `azure_key_vault`, `gcp_secret_manager` or `hashicorp_vault`;
- `reference_namespace`;
- `reference_name`; and
- optional `reference_version`.

The service hashes the authentication kind and normalized locator into `locator_hash`, then binds it with the exact profile hash and request facts.

One SFTP profile can have only one credential-reference binding. A materially different replacement requires a new governed profile rather than silent credential rebinding.

## Lifecycle

- `pending_second_approval -> active`
- `pending_second_approval -> rejected`
- `active -> disabled`

Receipts are append-only and hash-chained.

Exact replay returns the existing binding. Changed replay conflicts.

Pending/active custody fails closed when the source profile is no longer active. Rejected/disabled custody remains readable for historical audit.

## API

- `POST /api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/approve`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/reject`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/disable`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/receipts`

All endpoints require Admin + MFA.

## Safety boundary

The phase stores a reference only. It does not:

- store password/private-key/passphrase bytes;
- resolve a secret-manager reference;
- perform DNS or network connection attempts;
- authenticate to SSH/SFTP;
- create an SFTP session;
- list or read remote files;
- write, rename or delete remote content;
- stage content;
- admit Evidence or create Documents;
- enqueue downstream processing;
- execute AI; or
- mutate Claims.

The database records these non-authorities explicitly and constrains them to remain false.

## Acceptance

- active SFTP profile required;
- non-SFTP/pending/disabled profile fails closed;
- tenant isolation;
- authentication-kind validation;
- canonical backend/namespace/name/version handling;
- unknown-field and secret-like input rejection;
- four-eyes approval;
- exact replay and changed replay conflict;
- rejection and explicit disable;
- receipt-chain integrity and tamper rejection;
- active custody fails closed after profile disable;
- historical disabled/rejected custody remains readable;
- no secret/network/provider/Evidence/Document/processing/AI/Claim execution.

## Next boundary

Phase 17.6-C may add a narrowly scoped SFTP credential-reference resolvability/health qualification. File listing and content reads remain separately authorized future boundaries.

See ADR-242 and issue #535.

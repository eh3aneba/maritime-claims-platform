# Phase 17.5-B — Governed read-only external source discovery

## Goal
Add an auditable metadata-only discovery layer for active SharePoint and Google Drive source profiles created under Phase 17.5-A, without granting file-download, synchronization, Evidence, Document or claim authority.

## User-visible capability
An Admin + MFA actor can request a bounded discovery against an active governed source profile. A successful run records which remote items were listed as normalized metadata and exposes the immutable run, item manifest and receipt chain through tenant-scoped API endpoints.

## API
- `POST /api/v1/external-document-sources/profiles/{profile_id}/discoveries`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/discoveries/{run_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/discoveries/{run_id}/items`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/discoveries/{run_id}/receipts`

A request supplies an idempotency `request_key` and `max_results` from 1 to 500.

## Adapter posture
Phase 17.5-B defines a provider-neutral metadata adapter contract but registers no production SharePoint or Google Drive adapter by default. Consequently this phase cannot initiate live provider traffic unless a later, separately governed deployment explicitly registers an adapter.

Tests use deterministic in-process adapters to exercise the complete execution and integrity path.

## Stored metadata
A discovered item may contain only:
- provider item id;
- optional parent item id;
- display name;
- file/folder kind;
- optional MIME type;
- optional byte size;
- optional modified timestamp; and
- optional opaque provider ETag.

There is no raw content field, token field, download URL, synchronization cursor or Evidence reference.

## Integrity model
Every run binds:
- organization and profile id;
- provider and exact Phase 17.5-A profile hash;
- request key and result bound;
- adapter identity;
- deterministic item hashes;
- manifest hash; and
- final run hash.

The lifecycle receipt chain is exactly `requested → completed`. Reads and replays recompute the entire chain and fail closed on drift, truncation, reordering or metadata mutation.

## Safety invariants
A completed run may set `remote_list_performed=true`. All other authority flags remain false by database constraint and service verification:
- credential storage;
- OAuth/token exchange;
- raw remote read;
- remote write/delete;
- subscription creation;
- sync execution;
- Evidence admission;
- Document creation;
- claim mutation;
- live connection authorization.

## Acceptance coverage
- active profile required for new execution;
- provider adapter disabled by default;
- bounded deterministic metadata listing;
- exact idempotent replay;
- conflicting replay rejection;
- tenant isolation;
- item tamper detection;
- receipt truncation detection;
- no Claim or Document creation; and
- full migration/CI/E2E/policy/performance/supply-chain gates.

## Explicitly out of scope
- credential vaulting;
- OAuth authorization code or refresh-token flows;
- Microsoft Graph or Google Drive SDK/network clients;
- file download or content hashing;
- scheduled synchronization or checkpoints;
- automatic Evidence admission;
- Document creation; and
- claim mutation.

See ADR-206 and issue #404.

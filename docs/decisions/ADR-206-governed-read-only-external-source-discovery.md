# ADR-206: Separate metadata-only external-source discovery from ingestion authority

## Status
Accepted for Phase 17.5-B implementation.

## Context
Phase 17.5-A established governed SharePoint and Google Drive source profiles without granting any provider-connection or remote execution authority. The next useful capability is to determine which remote items exist inside an approved scope. Treating that metadata enumeration as equivalent to downloading content or admitting Evidence would create an unsafe authority jump.

The platform therefore needs an auditable discovery boundary that can prove a bounded remote list occurred while proving, at the same time, that no credential material, file bytes, synchronization state, Evidence, Document or claim mutation entered the system.

## Decision
Phase 17.5-B introduces synchronous, metadata-only discovery runs bound to an exact governed source profile.

A new discovery requires:

- an intact Phase 17.5-A profile;
- `active` profile status for a new execution;
- an Admin + MFA requester;
- a caller-supplied idempotency `request_key`;
- a bounded `max_results` of 1–500; and
- an explicitly registered provider adapter.

There are no production adapters registered by default. Therefore merging Phase 17.5-B does not itself enable SharePoint or Google Drive network access. Provider-specific connection/credential work remains a later authority phase.

### Adapter boundary
The adapter contract can return only normalized metadata: provider item id, optional parent id, display name, file/folder kind, optional MIME type, size, modified time and opaque provider ETag. It cannot return raw file bytes, download URLs, credentials, access tokens or mutation commands through the governed persistence contract.

Acceptance tests use deterministic in-process adapters. A real adapter must be authorized separately before registration in a deployment.

### Immutable execution evidence
Every successful discovery stores:

- the exact profile hash and provider;
- request key and result bound;
- adapter identity;
- a SHA-256 scope hash;
- deterministic item ordering and one SHA-256 hash per metadata item;
- a SHA-256 manifest hash;
- a SHA-256 run hash; and
- a two-event hash-chained receipt lifecycle: `requested → completed`.

Reads and idempotent replays recompute profile lineage, scope, item hashes, manifest, run hash and receipt chain. Missing, reordered, truncated or modified evidence fails closed.

### Safety boundary
A completed discovery may record only `remote_list_performed=true`. Database constraints keep all of the following false on runs and receipts:

- credential storage;
- OAuth/token exchange;
- raw remote read;
- remote write/delete;
- provider subscription creation;
- synchronization/checkpoint execution;
- Evidence admission;
- Document creation;
- claim mutation; and
- live provider-connection authority.

Discovery items contain metadata only and have no content/blob field.

### Replay and profile lifecycle
An exact completed request-key replay returns the existing integrity-verified run and performs no new remote list. A conflicting replay fails closed. New discovery requires an active profile. Historical completed runs remain readable after later profile disablement, provided the profile identity and both profile/discovery evidence chains remain intact.

## Consequences
The platform can now model and audit bounded remote enumeration independently from provider credential custody and evidence ingestion. This creates a narrow bridge from governed configuration to future enterprise connectors without granting download or mutation authority prematurely.

## Verification
Release requires migration-chain validation plus API/service coverage for active-profile gating, disabled-by-default adapters, deterministic listing, bounded results, exact replay, request-key conflicts, tenant isolation, item/receipt tamper detection and zero Evidence/Document/claim authority.

References: #404, ADR-205.

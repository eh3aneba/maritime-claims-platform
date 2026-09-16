# ADR-217: Transient bounded remote file-content read proof

- **Status:** Proposed for Phase 17.5-M
- **Issue:** #427
- **Depends on:** Phase 17.5-L / PR #426

## Context

Phase 17.5-L can perform one bounded live metadata listing for a governed SharePoint or Google Drive source and persist a fixed non-content projection. It cannot read a remote file body.

The next authority increase must prove that the platform can retrieve one exact listed file without silently turning that retrieval into durable ingestion, synchronization, Document creation or Evidence admission.

## Decision

Phase 17.5-M permits one remote file-content read for one exact `file` metadata item already persisted by one integrity-valid Phase L execution.

The request identifies only:

- the local Phase L listing execution UUID;
- the local Phase L metadata-item UUID;
- a bounded request key and human reason.

It cannot supply a provider item identifier, provider URL, download URL, HTTP headers, byte range, token or content body.

### Exact lineage

Before the remote read, M revalidates the complete A→L lineage through Phase L's integrity verifier. It binds the new execution to:

- Phase L execution scope/request/completion hashes;
- the Phase L item-set hash;
- the exact metadata-item hash and local UUID;
- provider/profile/credential-reference lineage;
- the governed provider client kind;
- the provider-derived read operation and endpoint-policy hash.

A folder is never eligible. One metadata item may produce at most one successful Phase M execution. Exact replay is idempotent and does not make a second provider call.

## Transient content boundary

Remote file bytes are the only new transient data authority.

The adapter may return a bounded byte body to the Phase M service. The service immediately:

1. verifies the actual byte count against the 8 MiB phase limit;
2. verifies declared Phase L size when present;
3. verifies bounded media-type consistency;
4. verifies the observed provider version-token hash when Phase L recorded one;
5. computes SHA-256;
6. discards the byte-bearing adapter result before durable completion facts are written or returned.

There is deliberately no database column, API field, audit field, receipt field, local file, cache entry or job payload that can hold the remote body.

Phase M also does not parse, OCR, decompress, render, execute or extract text from the content.

## Provider network policy

The provider endpoint is derived only from the governed profile and exact persisted Phase L item.

- **SharePoint:** the approved operation is the exact drive-item content read. Microsoft Graph remains the governed origin. If the protocol requires a provider-issued content redirect, it is bounded to one HTTPS provider-internal hop and the redirect target/header never crosses the adapter boundary.
- **Google Drive:** the approved operation is the exact `files.get` media equivalent under the governed Drive boundary. Google-native export is not authorized in M. Redirects are not authorized by the Google Drive M policy.

The adapter registry is empty by default and registration rejects provider/client/operation/origin/redirect-policy drift.

## Durable proof

Only non-content proof is durable:

- content SHA-256;
- exact byte count;
- bounded media-type class;
- observed version-token hash where available;
- latency class;
- exact A→L and metadata-item lineage hashes;
- append-only requested/completed receipts.

The content digest is an integrity proof, not a local Document or Evidence object.

## Explicitly unauthorized

Phase 17.5-M does not authorize:

- durable remote-content staging or blob storage;
- returning file bytes or extracted text through the API;
- synchronization/checkpoint state or background polling;
- recursive archive/resource retrieval;
- local Document creation;
- Evidence admission or Claim Fact creation;
- remote upload/edit/move/rename/delete;
- claim mutation;
- automated coverage, causation, liability, fraud, reserve or settlement decisions.

## Failure semantics

Missing adapters, folder items, lineage drift, tenant mismatch, invalid provider policy, oversized content, provider failure, media/version drift and malformed adapter results fail closed. Failed attempts are rolled back so no durable completed M artifact remains.

Adapter exceptions are sanitized before crossing the service boundary. Credential material, tokens, client/session objects, raw provider responses, headers and provider-issued download URLs remain adapter-local.

## Consequences

M proves only that one exact previously listed file can be read and cryptographically observed under a bounded authority envelope. It intentionally does not make that content usable elsewhere in the product.

The next separately reviewed authority increase is durable remote-content staging plus synchronization/checkpointing. Local Document creation and Evidence admission remain later independent decisions.
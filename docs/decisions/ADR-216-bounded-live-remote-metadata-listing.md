# ADR-216: Bounded live remote metadata listing

## Status

Accepted for Phase 17.5-L implementation; production merge remains subject to exact-head validation and fresh explicit authorization.

## Context

Phase 17.5-K proves that the platform can construct a transient provider client and complete one bounded non-document network/authorization health qualification without allowing credentials, tokens, raw provider responses or reusable client/session objects to cross the adapter boundary.

The next useful capability is to observe what remote items exist inside an already-governed SharePoint or Google Drive source. This is the first Phase 17.5 step that intentionally permits a provider **data API** operation. That authority must therefore be narrower than general provider access and must not imply file-content access, synchronization or Evidence admission.

## Decision

Phase 17.5-L permits one successful, bounded, read-only **metadata listing** for one exact completed and integrity-valid Phase K execution.

The listing boundary is defined as follows:

- the provider, tenant/source profile and source boundary come only from the governed upstream profile;
- the endpoint and field projection are derived by server policy, not supplied by the caller;
- the adapter registry is empty by default and fails closed;
- one successful listing is permitted per exact Phase K execution;
- exact replay is idempotent and must not perform another provider request;
- changed replay and second consumption fail closed;
- one provider page is permitted, with at most 100 projected items and a bounded response budget;
- redirects are disabled and provider origins are fixed;
- failed attempts roll back their requested execution/receipt state.

### Allowed metadata projection

Only a fixed projection may cross the adapter boundary:

- provider item identifier;
- parent identifier where available;
- item kind (`file` or `folder`);
- normalized display name;
- bounded MIME/type class where available;
- bounded byte size where available;
- modified timestamp where available;
- an already non-secret 64-hex version-token hash where available.

No arbitrary provider metadata map is accepted or persisted.

### Content and secret boundary

The following remain inside the adapter invocation and must never be returned, persisted, logged, cached, fingerprinted or included in receipts/audit details:

- credential material;
- authorization codes and access/refresh/ID tokens;
- provider client/session objects;
- raw provider response bodies;
- file bodies, content streams or parsed document text;
- download, export or upload URLs;
- unrestricted provider metadata.

The application service receives only the fixed metadata projection and bounded listing summary.

### Provider-specific policy

For SharePoint, Phase L permits only one metadata projection from the governed site/library boundary using the fixed Microsoft Graph origin. The operation may enumerate bounded children metadata but may not call a `/content` endpoint or any write/upload endpoint.

For Google Drive, Phase L permits only a `files.list`-equivalent metadata projection within the governed shared-drive/folder boundary using the fixed Google API origin. `alt=media`, export/download and all write operations remain prohibited.

### Persistence and integrity

The execution stores only governed lineage, policy hashes, request/completion hashes, bounded counts and status. Individual metadata projections use explicit columns rather than raw JSON. Every item has a deterministic hash; the ordered item-hash set is itself hashed and included in the completion proof. Requested/completed receipts remain append-only and hash chained.

Every later read revalidates the complete active A→K lineage plus Phase L execution, item-set and receipt integrity.

## Consequences

Phase L intentionally sets `remote_list_performed=true` only after a successful listing and may mark transient client construction as performed for that invocation.

It does **not** authorize:

- remote file-content read/download/streaming;
- local Document creation;
- Evidence admission;
- synchronization or checkpoint state;
- subscriptions or background follow-up reads;
- remote upload/edit/move/rename/delete;
- claim mutation;
- coverage, liability, causation, fraud, reserve or settlement decisions.

Those are later authority increases and require separate review, acceptance coverage, exact-head validation and merge authorization.

# Phase 17.5-L — bounded live remote metadata listing

Phase 17.5-L is the first external-document integration phase that permits a narrowly scoped provider data-API operation.

## What Phase L proves

For one exact completed Phase K provider-client health execution, an organization administrator may request one bounded, read-only remote metadata listing. The service revalidates the complete active A→K lineage, derives the provider endpoint and source boundary from the governed profile, invokes an explicitly registered adapter, persists only a fixed non-content metadata projection, and records deterministic requested/completed receipts.

A successful Phase L execution proves only that:

- one approved metadata-only list operation was performed against the governed source boundary;
- no more than one page and 100 items crossed the adapter boundary;
- the returned items were reduced to the approved fixed metadata projection;
- the persisted ordered item set is hash-protected;
- exact replay does not repeat the provider call.

## What may be returned

A remote item may expose only:

- provider item ID;
- parent item ID;
- file/folder kind;
- display name;
- MIME/type class;
- byte size;
- modified timestamp;
- a bounded version-token hash.

The execution may also expose item count, page count, truncation state and integrity hashes.

## What never crosses the adapter boundary

Phase L does not return or persist:

- credentials or secrets;
- authorization codes or access/refresh/ID tokens;
- provider client/session objects;
- raw provider response bodies;
- file bodies or document text;
- download/export/upload URLs;
- arbitrary unrestricted provider metadata.

Errors are mapped to bounded failure messages so provider exceptions cannot leak secret, client, response-body or file-content material.

## Provider scope

### SharePoint

The tenant/site/library boundary is inherited from the approved source profile. The service derives a fixed Microsoft Graph metadata-list endpoint and fixed field projection. It cannot call a file `/content` endpoint and cannot perform a write operation.

### Google Drive

The shared-drive/folder boundary is inherited from the approved source profile. The service derives a `files.list`-equivalent metadata query with a fixed field projection. It cannot use `alt=media`, export/download, upload or any write operation.

## Hard limits

- one successful Phase L execution per exact Phase K execution;
- one remote page;
- maximum 100 projected items;
- maximum provider-response budget defined by server policy;
- HTTPS fixed provider origins only;
- redirects disabled;
- exact replay idempotent;
- changed replay and second consumption rejected;
- failed execution rolled back.

## Still not authorized

Phase L still cannot:

- read or download remote file contents;
- create a local Document from a remote item;
- admit a remote item as Evidence;
- create checkpoints, synchronization state or subscriptions;
- schedule automatic follow-up reads;
- upload, edit, move, rename or delete remote content;
- mutate a claim;
- make coverage, causation, liability, fraud, reserve or settlement decisions.

Remote file-content read is the next separate authority boundary. Synchronization/checkpointing and Evidence admission remain subsequent independent phases.

## Merge control

Phase L is not production-complete until its exact reviewed PR head passes the complete backend, PostgreSQL migration/Alembic/preflight, frontend, dependency-lock, Compose, MT ORION E2E, performance, production-policy and supply-chain-security gates. A production merge still requires fresh explicit user authorization pinned to that exact head SHA.

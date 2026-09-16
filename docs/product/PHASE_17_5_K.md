# Phase 17.5-K — Bounded provider-client construction and network-health qualification

## Goal
Prove that one exact completed Phase J lineage can construct a transient provider client and perform one narrowly allowlisted non-document network/authorization health qualification without creating reusable client custody or remote-document authority.

## What Phase K adds

- one organization-admin-only execution path bound to one completed Phase J token-acquisition execution;
- complete A→J lineage revalidation before first execution and on later reads;
- Phase J row locking before first successful Phase K execution;
- one successful Phase K execution per exact Phase J execution;
- exact replay idempotency without a second adapter/network call;
- provider-derived client and health-operation policy;
- an empty-by-default, fail-closed provider-client-health adapter registry;
- fixed HTTPS provider origins, redirect rejection, bounded timeout/response budgets and sanitized failures;
- secretless/non-client persistence with deterministic request/completion hashes and append-only receipts;
- tenant-scoped read/receipt endpoints and bounded audit logging.

## Provider policy

### SharePoint / Microsoft Graph

- client kind: `microsoft_graph_transient_v1`
- token-flow lineage: `client_credentials`
- health operation: `graph_organization_health`
- fixed provider origin: `https://graph.microsoft.com`
- bounded health endpoint policy: Microsoft Graph organization health only

### Google Drive

- client kind: `google_drive_transient_v3`
- token-flow lineage: `jwt_bearer`
- health operation: `drive_about_health`
- fixed provider origin: `https://www.googleapis.com`
- bounded health endpoint policy: Drive about/authorization health only

Callers cannot supply or override provider origins, endpoint URLs, token flow, audience, client kind or health operation.

## Custody boundary
The adapter may use credential material, tokens, provider response bodies and a transient provider client internally. These never cross the adapter call and are never returned or persisted.

The application receives only:

- provider/client/health-operation kind;
- adapter kind;
- non-secret policy hash;
- `healthy` completion proof;
- bounded latency class;
- deterministic lineage/request/completion hashes;
- append-only requested/completed receipts.

## Still not authorized
Phase K does **not** permit:

- reusable provider-client/session storage;
- returning or persisting credentials, assertions, tokens or provider response bodies;
- listing SharePoint sites/libraries/folders/files or Google Drive files/folders;
- remote document metadata/list/read;
- file download/upload;
- synchronization, subscriptions or checkpoints;
- Document creation or Evidence admission;
- claim mutation;
- automated claims decisions.

## Failure behavior
Missing adapters, unsupported provider/operation/origin combinations, negative provider results, timeouts, malformed/oversized results and adapter exceptions fail closed. The request transaction is rolled back, so no durable completed Phase K row or receipt survives.

## Replay and integrity
Exact replay returns the completed execution without a second adapter invocation. Changed replay or a second request key for the same Phase J execution conflicts. The execution and its two-receipt chain are rehashed on reads, and upstream A→J invalidation causes Phase K to fail closed.

## Acceptance boundary
The Phase K acceptance path covers missing adapter, wrong origin, negative/timeout/malformed/oversized outcomes, exception sanitization, strict request fields, tenant isolation, success, replay, tamper detection, upstream invalidation and unchanged Claim/Document counts.

## Next authority boundary
Live remote metadata listing is still separate. Remote file read, synchronization/checkpointing and Evidence admission remain later independent phases requiring their own exact-head validation and fresh explicit merge authorization.

See ADR-215 and Issue #423.
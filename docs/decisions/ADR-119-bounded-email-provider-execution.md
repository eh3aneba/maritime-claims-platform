# ADR-119: bounded external email provider execution

- Status: Accepted for Phase 15.2
- Date: 2026-09-06
- Parent: #214
- Tranche: #217
- Follows: ADR-118 / Phase 15.1 provider source authority

## Context

Phase 15.1 established that an inbound provider message is staged against an exact configured provider adapter and that a configured adapter cannot be bypassed through the legacy connection-only normalized webhook. Microsoft Graph and Gmail adapters nevertheless remained configuration/operations records without pull execution authority.

A live-provider boundary must add useful read execution without making Microsoft Graph, Gmail or a provider credential a source of canonical claim truth. It must also avoid persisting bearer credentials or raw provider continuation cursors in the application database.

## Decision

### 1. Provider execution is explicit, manager-only and pull-only

`microsoft_graph` and `gmail_api` adapters may be executed through the dedicated adapter execution endpoint only when:

- the adapter is active;
- its consented ingestion connection is active;
- the caller has Admin or Claims Manager authority;
- `messages.read.allowed_folder` is present in the configured permission manifest.

`provider_webhook` has no pull execution authority. Provider execution performs HTTPS GET requests only. Sending, mutation, deletion, moving, marking read and subscription creation are outside this authority.

### 2. Credentials remain external references

The adapter database row continues to store only a credential reference.

Phase 15.2 resolves `env://NAME` at execution time from process environment and keeps the resolved bearer value in memory only for the provider calls. The access token is never written to application database rows, audit records or execution responses.

`vault://` and `secret-manager://` remain valid configuration references but fail closed at execution until dedicated resolvers are separately implemented. This avoids pretending that a reference scheme is operational merely because it is syntactically accepted.

### 3. Provider network destinations are allowlisted

The built-in provider transport accepts HTTPS GET calls only to:

- `graph.microsoft.com`;
- `gmail.googleapis.com`.

Microsoft Graph continuation links are additionally constrained to the configured mail-folder delta path. Gmail page tokens are only interpolated into a newly constructed request that retains the configured label scope.

This prevents an opaque continuation value from becoming an SSRF or cross-folder authority escape.

### 4. Microsoft Graph is selected-folder delta read

The Graph executor reads the configured folder through the messages delta endpoint and requests only fields needed for normalized inbound correspondence. When `attachments.metadata.read` is present, it may request attachment metadata with an explicit field selection that excludes attachment content bytes.

The transport does not call `sendMail`, attachment `$value`, message mutation or other write endpoints.

### 5. Gmail is selected-label read

The Gmail executor lists messages under the configured label and reads each selected message using `format=full` so headers, plain-text inline body data and attachment manifests can be normalized.

Attachment parts are represented only by filename, MIME type and declared size. The executor does not call the Gmail attachment-download endpoint and therefore does not acquire attachment bytes.

### 6. Existing staging authority remains authoritative for provider intake

Provider messages are normalized into `NormalizedEmailInput` and passed through the Phase 15.1 staging function. Therefore:

- the exact `adapter_id` remains source provenance;
- replay content/source integrity remains enforced;
- claim-reference matching remains suggestion-only;
- no Claim Correspondence is created automatically;
- no claim is linked automatically;
- attachment manifests remain `blocked_pending_quarantine`;
- attachment bytes are not admitted.

Canonical Correspondence promotion remains an explicit human review action.

### 7. Provider checkpoints are ephemeral outside the database

The execution request may carry an opaque provider checkpoint and the first successful response may return the provider's next checkpoint. Raw checkpoint values are not persisted.

The database stores only SHA-256 checkpoint hashes in the existing adapter/run fields. If an adapter has a checkpoint hash, a later execution must provide the exact checkpoint whose hash matches it. A missing or mismatched checkpoint fails closed before provider access.

A completed Gmail page with no next page token clears the stored checkpoint hash and permits a fresh label-scoped reconciliation pass. Microsoft Graph delta links remain the next incremental checkpoint.

### 8. Execution idempotency prevents duplicate provider fetches

`(adapter_id, idempotency_key)` remains the execution idempotency boundary. Repeating a completed key returns the existing run and does not call the external provider a second time. Because raw next checkpoints are deliberately not stored, an idempotent replay does not re-disclose a previous checkpoint.

### 9. Operational failures are content-free

Provider transport/credential/payload failures are represented by fixed summaries such as:

- `credential_reference_unresolved`;
- `credential_resolver_unavailable`;
- `provider_http_error`;
- `provider_transport_error`;
- `provider_payload_invalid`;
- `provider_staging_rejected`.

Audit metadata records provider kind, status, counts and checkpoint presence only. Message subjects, bodies, sender/recipient content, bearer values and opaque checkpoint values are excluded.

## Consequences

### Positive

- Graph/Gmail gain bounded real pull execution authority without gaining claim-record authority.
- Provider credentials remain out of the application database.
- Provider continuation state cannot silently jump to a different configured Graph folder.
- Existing replay, tenant, human-review and attachment quarantine boundaries are reused rather than duplicated.
- A provider execution can be retried/reconciled without automatically creating canonical claim records.

### Trade-offs

- Phase 15.2 does not implement OAuth refresh, Vault or Secret Manager clients. Deployments must provision a usable runtime credential reference separately.
- Raw checkpoints must be retained by the authenticated execution caller/orchestrator between successful continuation requests because only hashes are stored in the application database.
- Gmail reconciliation relies on provider message identity plus existing staging deduplication after page-token pagination completes.
- No background scheduler is introduced in this tranche.

## Explicitly deferred

The following require separate authority/security design and are not implied by this ADR:

- OAuth authorization and refresh lifecycle;
- Vault/Secret Manager integrations;
- provider push subscription lifecycle;
- background worker/scheduler deployment;
- email send authority;
- attachment-byte acquisition;
- malware/quarantine/storage admission;
- automatic claim linking or Correspondence promotion;
- any coverage, causation, fault, liability, fraud, recoverability, governing-law, legal time-bar effect, reserve, settlement, payment or claim-closure authority.

# ADR-118: Email provider source authority and replay integrity

- **Status:** Accepted for Phase 15.1
- **Date:** 2026-09-06
- **Decision scope:** normalized inbound email staging only
- **Parent:** #214
- **Implementation tranche:** #215

## Context

MCRI already has consent-gated mailbox connections, normalized inbound email staging, human claim-link review, attachment manifests that remain blocked pending quarantine, provider adapter configuration, and a governed Correspondence workflow.

Before this decision, normalized webhook intake was authenticated only by the connection ingestion token. Provider adapters described intended sources and least-privilege permissions, but they were not part of the message provenance boundary. The legacy intake also treated any repeated `(connection_id, provider_message_id)` as an idempotent retry before checking whether the normalized content was actually identical.

Those behaviors are acceptable for an early controlled normalized-webhook pilot but are not a safe foundation for live mailbox/provider execution. A configured provider must not be bypassable, and a provider identity collision with changed content must not silently reuse an older staged record.

## Decision

### 1. Provider-bound staging identity

New staged inbound messages may carry `adapter_id`, identifying the exact configured `EmailProviderAdapter` that was authorized to submit the normalized message.

The column is nullable for backward compatibility. Historical connection-only rows predate provider source authority, so MCRI does not retroactively invent provider provenance for them.

### 2. Adapter-bound normalized webhook route

A provider-bound normalized webhook is accepted only when all of the following are true:

- the adapter exists;
- its underlying consented connection exists and is active;
- the supplied connection ingestion token is valid;
- adapter and connection belong to the same organization;
- the adapter itself is active; and
- `provider_kind` is `provider_webhook`.

`microsoft_graph` and `gmail_api` adapter records remain configuration-only in Phase 15.1. They do not gain execution authority merely because an adapter row exists. Live Graph/Gmail execution requires a later explicit provider-execution and credential-boundary decision.

### 3. Legacy route becomes fail-closed after provider configuration

The existing connection-only normalized webhook remains available only for a legacy connection that has no provider adapter configured.

Once any provider adapter is configured for that connection, the generic route rejects intake. This prevents adapter policy from being bypassed while preserving compatibility for legacy normalized-webhook connections during migration.

A revoked or suspended configured adapter does not reopen the legacy route. Provider configuration is a source-authority boundary, not a temporary routing preference.

### 4. Replay integrity

MCRI computes the deterministic normalized content hash before resolving a duplicate provider message identity.

For the same `(connection_id, provider_message_id)`:

- same content hash **and** same provider-source binding => idempotent replay; return the existing staged record;
- different content hash => reject with `409`;
- different provider-source binding, including a historical legacy row being replayed through a new adapter => reject with `409`.

A provider identity collision never overwrites the existing staged message and never silently rebinds provenance.

### 5. Conflict telemetry is content-free

Replay-conflict audit records may contain only compact operational/source metadata such as connection ID, existing/incoming adapter ID and a bounded reason code. They must not contain message body, subject, sender, recipients, claim evidence, credentials, secrets or the incoming normalized payload.

### 6. Provider staging remains non-authoritative

This ADR does not change the existing human authority model:

- a claim-reference match remains a suggestion only;
- inbound messages remain `pending_review` staging records;
- no canonical Correspondence is created during provider intake;
- a human handler must explicitly confirm claim linkage and promotion to Correspondence;
- attachment metadata remains `blocked_pending_quarantine`;
- attachment bytes are not admitted by this route.

An external email provider therefore supplies candidate source material, not a canonical claim decision or claim-record mutation authority.

## Consequences

### Positive

- provider configuration becomes enforceable rather than descriptive;
- changed-content replay cannot silently masquerade as an idempotent retry;
- historical provenance is preserved without fabrication;
- Graph/Gmail execution cannot arrive accidentally through a generic webhook;
- the design establishes a safe boundary for a later live-provider execution tranche.

### Trade-offs

- a connection that gains an adapter must migrate callers to the adapter-specific route;
- historical connection-only messages cannot be automatically rebound to a new adapter;
- source binding is intentionally strict even when the normalized content is identical.

## Deferred work

Phase 15.1 intentionally does not implement:

- Microsoft Graph or Gmail network/API execution;
- OAuth acquisition/refresh;
- provider send authority;
- attachment-byte download, malware scanning or evidence admission;
- provider checkpoint/reconciliation workers beyond the existing bounded operations records;
- autonomous claim linkage or Correspondence promotion.

Those capabilities require separate authority/security review under #214.

## Permanent authority guardrails

This provider layer must not autonomously determine coverage, causation, fault, liability, fraud, recoverability, governing law, legal time-bar effect, reserve, settlement, payment or claim closure. Canonical Claim Facts, Correspondence, Technical, Financial, Recovery/Time-Bar, Assessment, Adjustment, Reserve, Settlement and Payment retain their existing authority boundaries.

## Verification

Phase 15.1 requires regression tests for provider binding, exact replay, changed-content conflict, source mismatch, legacy-route bypass prevention, inactive adapters, Graph/Gmail non-execution, unchanged human promotion rules and blocked attachment admission. The production PR must also pass the repository's exact-head backend, migration/preflight, frontend, browser, performance, deployment-policy and supply-chain gates before merge authorization.

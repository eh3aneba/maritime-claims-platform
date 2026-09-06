# ADR-120: Provider execution-state authority and reconciliation

- **Status:** Accepted
- **Date:** 2026-09-06
- **Phase:** 15.3
- **Parent:** #214

## Context

Phase 15.1 bound staged inbound email to an explicit provider source and added replay integrity. Phase 15.2 then introduced bounded pull-only execution for Microsoft Graph and Gmail while keeping credentials and opaque provider checkpoints outside canonical application persistence.

The pre-existing adapter operations API also allowed a manager to manually record an `EmailAdapterRun`. Before live provider execution existed this was operations metadata. After Phase 15.2, however, that path could also move `checkpoint_hash`, `last_sync_at` and `next_sync_at` from operator-supplied values without a provider fetch. Those fields now participate in provider execution integrity and therefore require a narrower authority boundary.

The repository also has `next_sync_at` metadata but no deployed scheduler/worker. Because raw provider checkpoints are intentionally not stored, the application must not imply that it can autonomously resume Graph/Gmail cursors that it does not possess.

## Decision

### 1. Live pull execution owns Graph/Gmail execution state

For `microsoft_graph` and `gmail_api`, provider execution state may only move through the governed `/execute` path plus explicit adapter lifecycle transitions.

The legacy manually-recorded run endpoint is rejected for those provider kinds. A manager therefore cannot manufacture a successful Graph/Gmail fetch or replace the expected checkpoint hash with an arbitrary value.

### 2. Provider webhooks have no pull checkpoint or pull schedule authority

`provider_webhook` may retain bounded run telemetry for external operational reporting, but:

- it cannot supply a provider checkpoint;
- its run records never contain a checkpoint hash;
- it has no `next_sync_at` pull schedule;
- free-form external failure text is not persisted; only the fixed code `provider_webhook_reported_failure` is stored.

### 3. Adapter lifecycle owns eligibility, not provider cursor material

New Graph/Gmail adapters begin due for an initial operator-driven pull. Suspending or revoking an adapter removes active due scheduling. Reactivating a Graph/Gmail adapter makes it due again without modifying its checkpoint hash. Webhook adapters remain unscheduled for pull execution.

Lifecycle transitions never create, replace or reveal an opaque provider checkpoint.

### 4. Provider failures use bounded scheduling backoff

A successful Graph/Gmail execution schedules the normal 15-minute next window.

Consecutive failed executions use deterministic exponential backoff based only on run status:

- first failure: 15 minutes;
- second: 30 minutes;
- third: 60 minutes;
- fourth and later: capped at 120 minutes.

This is scheduling metadata only. The application does not automatically execute the retry.

### 5. Reconciliation is an operator view, not a scheduler

A manager-only tenant-scoped reconciliation endpoint reports content-free operational state for Graph/Gmail adapters. It may expose:

- adapter/provider identity;
- adapter and consented-connection status;
- due/waiting/suspended/revoked/blocked/reconciliation-required state;
- last and next sync timestamps;
- last run status;
- bounded consecutive failure count;
- whether checkpoint handoff is required;
- that execution remains operator/external-orchestrator driven.

It must not expose:

- `credential_reference` or resolved credentials/tokens;
- `checkpoint_hash` or an opaque provider checkpoint;
- subject/body/sender/recipient data;
- attachments or claim evidence;
- privileged/legal content.

Four consecutive failed executions are surfaced as `reconciliation_required` even while the bounded retry timestamp remains available. An active pull adapter with missing scheduling metadata is also surfaced as requiring reconciliation.

## Consequences

### Positive

- Graph/Gmail execution state can no longer be forged through the legacy run API.
- Pull and webhook operational semantics are separated.
- Retry behavior is bounded without deploying a hidden background worker.
- Operators can see when a provider adapter is due, blocked or needs reconciliation without exposing provider secrets or claim content.
- The server remains honest about opaque checkpoint ownership.

### Trade-offs

- A production orchestrator must still supply the opaque checkpoint returned by the preceding successful execution.
- There is no automatic scheduler in this tranche.
- Vault/Secret Manager resolvers, OAuth refresh, provider push subscriptions and checkpoint-vault integration remain later authority decisions.

## Non-authority statement

This decision does not grant email send authority, attachment-byte admission, autonomous claim association, automatic Correspondence promotion, or any authority over coverage, causation, fault, liability, fraud, recoverability, governing law, legal time-bar effect, reserve, settlement, payment or claim closure.

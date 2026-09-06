# ADR-126: Explicit live-provider activation gate

- **Status:** Accepted
- **Date:** 2026-09-06
- **Phase:** 15.9
- **Issue:** #231

## Context

MCRI already separates configured provider adapters from claim-record authority, keeps Graph/Gmail credentials as external references, requires explicit checkpoint custody acknowledgement, and quarantines provider attachment bytes before any Evidence admission.

After Phase 15.8, however, a Graph/Gmail adapter could still be operationally `active` immediately after configuration. That lifecycle status means the source is configured and consented; it must not also imply permission to make live mailbox/network calls. A separate private-pilot readiness decision is required.

The repository currently has a runtime `env://` credential resolver. `vault://` and `secret-manager://` references remain intentionally unsupported until real repository-backed clients and deployment configuration exist. Phase 15.9 must not simulate those resolvers.

## Decision

### Separate configuration state from live-network authority

Graph and Gmail pull adapters have a non-secret `live_execution_enabled` state, with activation timestamp and actor metadata. New pull adapters default to disabled and unscheduled even when their ordinary adapter lifecycle status is `active`.

Normalized provider webhooks do not use this pull-activation model.

### Require an explicit local activation preflight

A Claims Manager/Admin may activate a Graph/Gmail adapter only when all of the following are true:

- the adapter is tenant-scoped and operationally active;
- its consented ingestion connection is active;
- selected-folder message-read permission is present;
- no checkpoint handoff is pending;
- the credential reference is structurally valid;
- its credential backend is supported by the current runtime; and
- the credential value resolves at activation time.

Activation also requires explicit confirmation and a human reason. The reason text, credential locator, resolved credential value, checkpoint value/hash, mailbox content and claim evidence are not persisted in activation audit metadata.

Activation performs **no Graph/Gmail network call** and stages no message or attachment.

### Guard every fresh provider-network path

A fresh Graph/Gmail mailbox execution must fail closed before credential resolution or network access unless live activation is enabled. Fresh provider attachment acquisition is governed by the same live-network authority.

Exact idempotent execution replay and replay of already-quarantined local attachment bytes remain local recovery operations and do not require current live-provider authority because they do not make a provider network call.

### Invalidate authority on material lifecycle changes

Live authority is cleared when:

- the provider credential reference is rotated;
- the adapter is suspended, revoked or subsequently reactivated; or
- the associated consented connection transitions state.

Invalidation clears only live-network authority and scheduling. It does not rewrite provider checkpoints, staged messages, canonical Correspondence, Evidence, Claim Facts or other claim state. A fresh explicit activation is required before new provider network access.

### Reconciliation remains content-free

Operational reconciliation may expose only bounded activation state and blocker codes such as:

- `operator_activation_required`;
- `credential_resolver_unavailable`; or
- `credential_reference_invalid`.

It must not expose credential locators/values, raw checkpoints or hashes, mailbox content, attachment bytes, claim evidence or privileged/legal text.

## Consequences

- An adapter being `active` no longer implies live mailbox authority.
- Deployment/runtime readiness is confirmed separately and explicitly.
- Unsupported Vault/Secret Manager references remain fail-closed rather than being emulated.
- Credential rotation and lifecycle transitions require deliberate reactivation.
- Local replay/recovery remains available without reopening provider network authority.
- Existing human-only claim linking, Correspondence promotion, quarantine/Evidence admission and substantive claim-decision guardrails remain unchanged.

## Deferred work

Real Vault/Cloud Secret Manager clients, OAuth refresh/rotation orchestration and broader production identity lifecycle are explicitly outside this tranche. They require a separate deployment/identity design rather than an in-application fake resolver.

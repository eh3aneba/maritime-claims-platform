# ADR-081 — Content-free outbound governance webhooks

**Status:** Proposed for Phase 12I implementation validation  
**Date:** 2026-09-01

## Context

Phase 12H introduced a tenant-scoped AI Operations read model that intentionally exposes only governance-safe identifiers, hashes, status, lineage and operational metrics. Enterprise deployments may need those governance events in a SIEM or another control-plane system, but a generic webhook implementation could accidentally create a second raw-data export channel, persist credentials, enable SSRF or allow external systems to influence claim/AI authority.

## Decision

MCRI will provide a dedicated Phase 12I outbound webhook subsystem with the following constraints.

### 1. Phase 12H is the only initial event source

The delivery serializer consumes the existing content-free AI Operations projection. It does not query raw prompt, evidence, provider-output or claim text columns. A second explicit allowlist is applied before the outbound envelope is persisted.

### 2. Outbound only

There are no inbound webhook endpoints or command contracts. A receiver cannot approve/reject AI output, report/resolve incidents, pause/revoke authorization, alter ClaimFacts or change claim/legal/financial state through this subsystem.

### 3. Raw signing secrets are not persisted

Each destination stores a cryptographically random salt and monotonically increasing key version. The signing key is derived with HMAC from the MCRI application master secret plus organization/destination/version/salt context. The resulting secret is disclosed only on destination creation or rotation.

This avoids adding another plaintext application credential column while preserving deterministic worker access to the active key. Rotation retains only the prior salt/version for a short transition window.

### 4. SSRF controls are enforced twice

At configuration time, URLs must be HTTPS and may not contain credentials, fragments, localhost/local hostnames or literal non-global addresses. Immediately before a real delivery the worker resolves DNS and fails closed if any resolved address is non-global. HTTP redirects are not followed.

### 5. Reliable delivery is isolated from claims workflows

A separate worker synchronizes content-free source events into a delivery ledger and processes due rows. Source-event/destination/revision/envelope-version uniqueness provides idempotent enqueueing. Delivery failures use bounded exponential backoff and eventually dead-letter. The originating claim or AI transaction never waits for or depends on outbound delivery.

### 6. Persist only safe diagnostics

The ledger contains the content-free envelope, payload hash, signing-key version, status, attempt counts, timestamps, HTTP status and an allowlisted error code. Response bodies and arbitrary exception strings are not persisted.

### 7. Signed replay-resistant request contract

Canonical JSON is signed with HMAC-SHA256 over `timestamp.event_id.body`. Requests include a timestamp, event/idempotency ID, key version and envelope version. A verification helper enforces a bounded replay window.

## Consequences

### Positive

- Enterprise SIEM integration does not create a raw-data egress channel.
- A compromised or failing receiver cannot block claims workflows.
- Receivers can authenticate and deduplicate events without sharing MCRI login credentials.
- Destination state, retries and dead-letter behavior are auditable and tenant-scoped.
- Key rotation does not require persisting raw secrets.

### Trade-offs

- Deriving destination keys from the application master secret means a master-secret rotation requires an operational transition plan for webhook keys.
- Denying private-network targets by default prevents some on-premise integration patterns; those require a separately reviewed deployment/network policy rather than weakening the application default.
- The first release is webhook-generic rather than vendor-specific SIEM SDK integration.

## Rejected alternatives

- **Persist raw webhook secrets encrypted in the same application database:** rejected for the initial foundation because it introduces key-encryption/key-management complexity and another credential-at-rest surface.
- **Send directly from claim/AI request transactions:** rejected because receiver availability would affect core claims workflows.
- **Serialize ORM/source objects generically:** rejected because it risks raw-content leakage when models evolve.
- **Allow redirects/private targets for convenience:** rejected because it weakens SSRF boundaries.
- **Accept inbound SIEM commands:** rejected because observability must not create autonomous or external claims/AI authority.

## Revisit conditions

A future phase may revisit managed secret stores, private-network egress gateways, vendor-specific connectors or inbound control-plane commands only with a separate threat model, explicit authorization and tests demonstrating that MCRI claim/AI authority boundaries remain intact.

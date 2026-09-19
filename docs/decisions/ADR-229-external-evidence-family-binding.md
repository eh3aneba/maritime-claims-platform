# ADR-229: Durable external source-item Evidence family binding

## Status

Proposed by Phase 17.5-Y.

## Context

Phase 17.5-X admits one exact external file version into the canonical Document domain and
creates the initial Document with `document_family_id == document.id`. A future admitted
version of the same provider item needs a stable provider-agnostic family anchor without
continuing the generation-4/5/6 schema pattern.

## Decision

Persist one immutable source-item family binding after a verified Phase-X admission.

The binding derives its stable source identity from the trusted generation-3
`observed_provider_item_id_hash`, not from caller input. It binds that identity to the
existing initial Document family and records version 1 as the immutable baseline.

Phase Y performs no provider, object-storage, Evidence-byte, Document, processing, AI,
Claim or checkpoint mutation. Exact request-key replay is idempotent; altered replay and
attempts to bind the same source item or Document family again fail closed.

## Consequences

Later phases can admit version N+1 into the existing Document family using one generic
source-family anchor. Processing authority remains separate and must be explicitly
introduced by Phase 17.5-Z.

# ADR-239 — Human authorization before refreshed external Evidence admission

## Status

Accepted for Phase 17.5-AI.

## Context

Phase 17.5-AH can consume a human-approved changed-item refresh authorization, read one exact remote item and stage verified bytes into quarantine. AH deliberately does not mutate the canonical Evidence family.

Directly turning AH output into a new canonical Document would collapse remote refresh execution and Evidence admission into one authority boundary. That would make a scheduled external-source change capable of mutating Claim Evidence without a separate human admission decision.

## Decision

A completed AH refresh must pass through a new immutable admission-authorization record before any N+1 Document may be created.

The authorization is bound to the exact AH execution and immutable proof, tenant/Claim/profile, Evidence-family binding, stable source identity, expected current Document ID/version/file hash, content proof and storage-key hash.

Authorization requires Admin + current MFA and is authorization-only. It performs no provider or storage I/O, no malware scan and no canonical Document mutation.

One AH execution can produce at most one authorization. Exact replay is idempotent; conflicting replay fails closed. Current-family drift before authorization fails closed.

## Consequences

- Scheduled observation and refresh cannot silently mutate canonical Evidence.
- A later AJ execution can consume a narrow, auditable authority rather than deriving authority from AH execution alone.
- The raw quarantine object key remains internal.
- Processing and external-AI permissions remain independent.
- A later canonical version change does not rewrite historical authorization records; it simply makes any future AJ execution stale.

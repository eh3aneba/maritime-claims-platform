# ADR-230: Exact-current processing release for admitted external Evidence

## Status

Proposed by Phase 17.5-Z.

## Context

Phase X admits one explicitly authorized external file version into the canonical Claim Document domain.
Phase Y binds that admitted version to a durable provider-agnostic source-item/Document-family identity.
Both phases intentionally leave downstream content processing fail-closed.

A queued processing job cannot be treated as durable authority. Human processing authority must remain
separate from Evidence admission and must be revalidated immediately before worker execution.

## Decision

Persist one governed processing-release lifecycle for the exact current external Evidence family binding
and exact current Document version.

The initial release authorizes deterministic local text extraction/OCR-related processing only. The release
does not authorize external AI. AI jobs continue to require the independent AI runtime/governance control
plane in addition to the Evidence processing boundary.

Release authority is checked at both enqueue time and worker time. Revocation, stale/superseded/deleted
Document state, tenant/Claim/family/version drift or integrity failure causes processing to fail closed.
Security-only malware rescans remain available without a processing release.

The release action itself performs no provider or storage I/O, no Document mutation, no processing enqueue,
no Claim mutation and no AI execution. Grant/revoke decisions are receipt-backed and auditable.

## Consequences

Operators can explicitly hand admitted external Evidence into normal local processing without weakening the
admission boundary. Revocation takes effect for queued work because worker execution revalidates authority.
Future version N+1 admission must obtain a new exact-current release for the new Document version rather
than inheriting authority silently.

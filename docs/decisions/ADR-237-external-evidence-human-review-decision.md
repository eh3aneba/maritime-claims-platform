# ADR-237: Human review decision boundary for scheduled external observations

## Status
Proposed — Phase 17.5-AG.

## Context
Phase 17.5-AF turns completed `changed` and `missing` recurring observations into immutable pending human-review handoffs. AF intentionally grants no provider, content-read, storage, Document, Evidence, processing, AI or Claim mutation authority.

The next bridge must preserve that separation while allowing an authenticated human operator to decide what happens next.

## Decision
AG introduces an explicit human decision over one exact pending AF handoff.

- Only an organization Admin with current MFA may decide.
- The AF handoff is locked and revalidated before decision.
- Current Claim/profile/family binding/source authority is revalidated against the handoff snapshot; stale authority fails closed.
- `changed` supports `approve_refresh` or `dismiss`.
- `missing` supports `acknowledge_missing` or `dismiss`; it can never create refresh authority.
- A terminal decision is immutable and exactly-once per handoff.
- `approve_refresh` creates a narrow, unconsumed downstream authorization record bound to the exact handoff and current authority snapshot.
- AG itself does not construct a provider client, acquire a token, read remote metadata/content, access staging storage, mutate a Document, admit Evidence, enqueue processing, run AI, mutate Claim state, or advance a checkpoint.
- Future content-refresh execution must consume the narrow authorization in a separate phase and revalidate authority again.

## Concurrency
The exact AF handoff row is selected `FOR UPDATE`. A unique decision per handoff plus an immutable receipt prevents double decisions. Approval authorization is unique per decision and remains unconsumed in AG.

## Consequences
Human agency remains mandatory between metadata-only change detection and any future content read. Missing items cannot accidentally authorize content access. Historical AF evidence remains immutable while current authority is separately revalidated.

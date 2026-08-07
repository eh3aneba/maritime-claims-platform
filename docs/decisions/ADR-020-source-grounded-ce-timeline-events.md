# ADR-020 — Chief Engineer chronology uses source-grounded reported events

## Status
Accepted — Sprint 5 Phase B

## Context
The MT ORION pilot showed that the v1 Chief Engineer Report schema stored a single `incident.time` and separate `immediate_actions[]`. Chronology reused the incident timestamp for later actions, manufacturing false precision and creating artificial conflicts.

## Decision
- Chief Engineer Report extraction schema v2 includes `reported_events[]`.
- Every narrative event carries its own date/time/timezone/source fields.
- If a source does not state a usable event clock time, the event time remains null.
- Chronology may retain that reviewed event as undated/relative evidence; it must not copy `incident.time` into it.
- `reported_events[]` are repeatable evidence and are not promoted to scalar Claim Facts.
- Deterministic chronology phrase classification remains authoritative for the normalized event type.
- Duplicate candidates of the same event type derived from the same source statement are collapsed.

## Consequences
Chronology conflicts reflect source timing rather than schema artefacts. Historical v1 CE evidence remains supported through a conservative fallback that keeps non-initial actions undated instead of assigning the incident timestamp.

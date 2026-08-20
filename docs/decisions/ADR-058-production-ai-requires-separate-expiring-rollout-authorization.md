# ADR-058: Production AI requires a separate expiring rollout authorization

## Status

Accepted for Sprint 11E.

## Decision

A positive private-pilot exit recommendation does not authorize Production AI. Limited Production evaluation requires a new append-only authorization anchored to the exact recommended model bundle, four independent Security/Privacy/Product/Operations approvals and an Administrator decision.

The authorization is limited to non-Restricted Chief Engineer Reports and Engine Logs in a deterministic 1–10% document cohort, fixed claim/document/user/run caps and a maximum 14-day window. Queue and worker execution both fail closed unless the tenant, bundle, document, eligibility, rollout, quota, incident and monitor controls pass.

Every provider run is recorded without content and must be reviewed by a different human. Threshold failure or an incident pauses execution and triggers rollback. Incident resolution, a fresh passing monitor and explicit Admin resume are separate actions.

## Consequences

- Provider configuration, deployment, benchmark promotion, pilot completion and exit recommendation remain insufficient individually or together.
- Restricted documents, Production-wide use, rollout above the declared percentage, autonomous decisions and automatic authoritative-fact updates remain prohibited.
- The fixed window, cohort and thresholds cannot be relaxed by a client request.
- Authorization, eligibility, run, monitor and incident evidence is tenant-scoped, auditable and content-free.
- Completion produces evidence for a later stop/extend/graduation assessment; it never expands scope automatically.

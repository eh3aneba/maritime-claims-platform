# ADR-059: Limited-production graduation requires measured outcomes

## Status

Accepted for Sprint 11F.

## Context

Sprint 11E permits an explicitly authorized, expiring 1–10% Production evaluation for a pinned AI bundle. Completing that evaluation proves only that its bounded operational gate completed; it does not prove that the bundle should receive wider rollout.

A graduation decision needs evidence about usefulness, human overrides, unsupported outputs, source grounding, reviewer effort, latency, observed provider cost, trend stability and incidents. That evidence must not create a new store of claim or provider content.

## Decision

Add a separate append-only Sprint 11F outcome gate anchored to one completed Sprint 11E authorization and its exact decision hash/model/prompt/schema/rollout bundle.

Require one content-free observation for every reviewed provider run. Calculate deterministic cohort, workflow and first-half/second-half metrics. Block a positive result on threshold failure, unresolved High/Critical incidents, any Privacy/Security/Cross-tenant incident, incomplete review coverage or material second-half regression.

Require four distinct non-requesting Product, Quality, Risk and Operations reviewers, followed by an Admin recommendation-only decision.

## Consequences

- Sprint 11E completion can never automatically expand rollout.
- A passing Sprint 11F result still cannot authorize Production-wide AI.
- Restricted documents and new document classes remain unauthorized.
- Human review remains mandatory.
- Failed and historical assessments remain immutable.
- A later graduation/scale-up stage must be separately designed and authorized.

# ADR-060: Controlled AI scale-up requires separate authorization

- Status: Accepted
- Date: 2026-08-20

## Context

Sprint 11F can recommend that a larger Production cohort be considered after a completed limited-production evaluation meets fixed quality, grounding, safety, effort, latency and cost thresholds. A recommendation is evidence, not permission. Reusing the old 11E authorization or automatically increasing its rollout would bypass independent review of the larger operational exposure.

## Decision

A larger cohort is represented by a new Sprint 11G authorization object. It must anchor to the exact positive 11F assessment and decision hashes, inherit the measured model/prompt/schema bundle, use fresh document eligibility, receive five independent approvals and an Admin decision, expire, remain revocable, and enforce queue-time plus worker-time gates.

The allowed rollout is 11–25% only. Once a tenant has an 11G attempt, Production runtime cannot fall back to the older 11E control plane to bypass a pending, held, paused, revoked, completed or expired 11G state.

## Consequences

- A successful 11F recommendation cannot change Production traffic by itself.
- Existing 11E document eligibility is not reusable in 11G.
- Monitoring can pause the scale-up automatically but cannot expand it.
- Privacy, Security or Cross-tenant incidents prevent resume within the same authorization.
- Completion remains evidence only and grants neither Production-wide nor Restricted-document use.
- A future broader-production decision requires another separate control plane and explicit authorization.

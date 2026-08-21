# AI broader-production control plane

Sprint 11I is the newest Production AI runtime control plane after Sprint 11G. It is intentionally bounded rather than Production-wide.

## Evidence chain

`11F measured outcome -> 11G controlled scale-up -> 11H measured readiness recommendation -> 11I broader-production authorization`

An 11I authorization stores the exact 11H assessment hash and decision hash, the 11G authorization decision hash, the inherited 11F assessment/decision hashes, and the exact model/prompt/schema bundle. Runtime authorization revalidates that chain before every queue/worker decision.

## Precedence

In Production the shared AI runtime checks for any tenant-scoped 11I attempt first. If one exists, only a currently authorized, unexpired, anchor-valid 11I record may permit execution. No fallback to 11G/11E is allowed. Tenants without an 11I attempt continue through the existing 11G then legacy path.

## Data model

The module persists separate authorization, six-party approval, fresh document eligibility, run, monitor and incident ledgers. The control ledgers store content-free hashes, counters and bounded evidence references only; raw document text, prompts, provider responses, candidate answers and source quotes are excluded.

## Runtime admission

Admission requires an active 26–50% authorization, exact configured bundle, Internal/Confidential CE Report or Engine Log, deterministic rollout membership, fresh per-document eligibility, no open incident, no safety-boundary incident history, remaining run/user caps and—after the initial monitoring window—a fresh passing monitor.

## Human review

Each provider run is reserved before execution and can become `human_reviewed` only when a different user records the immutable outcome metrics. AI output never updates authoritative claim facts automatically.

## Monitoring and rollback

The live monitor computes human-review coverage, Reject/Edit rates, unsupported-output rate, source-grounding validity, P95 latency, mean provider cost and second-half grounding/latency/cost regression. Failed controls pause the authorization. Incidents also pause immediately. Non-safety recovery requires resolution, a fresh passing monitor and explicit Admin resume. Privacy/Security/Cross-tenant history requires a new attempt.

## Hard boundary

11I cannot authorize rollout above 50%, Production-wide AI, Restricted documents, new document classes, autonomous claim decisions, or automatic authoritative fact updates. A later measured Sprint 11J is required before considering any further stage.

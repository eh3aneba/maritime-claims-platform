# ADR-062: broader-production AI requires a separate bounded authorization

## Status
Accepted

## Context

Sprint 11H can recommend that a broader-production stage be designed, but a positive recommendation must not silently widen the live Production rollout. The next control plane needs a fresh authorization boundary with stronger organizational review and explicit runtime precedence.

## Decision

A Sprint 11I authorization is a new immutable control record anchored to the exact positive 11H assessment and decision hashes plus the inherited 11G/11F evidence chain. It may authorize only a deterministic 26–50% cohort for CE Report and Engine Log documents, for at most 30 days, with fixed caps and six independent non-requesting approvals before an Admin decision.

Once any 11I attempt exists for a tenant, 11I becomes the newest Production control plane. A held, paused, revoked, completed, expired, or otherwise invalid 11I attempt fails closed and cannot fall back to Sprint 11G or Sprint 11E.

Every provider output remains subject to different-human review. Monitor failure pauses execution and triggers rollback. Safety-boundary incident history blocks same-attempt recovery.

## Consequences

The system can widen real AI usage without equating a successful readiness assessment with permission to deploy. Operators gain a reversible 26–50% stage while Production-wide use, Restricted documents, new document classes, autonomous claim decisions and automatic authoritative fact updates remain explicitly unauthorized.

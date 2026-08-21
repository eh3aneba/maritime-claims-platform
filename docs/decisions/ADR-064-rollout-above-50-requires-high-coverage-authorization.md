# ADR-064: Rollout above 50% requires a separate high-coverage authorization

## Status
Accepted

## Decision
Sprint 11J recommendation is evidence, not permission. Introduce Sprint 11K as a separate 51–75% Production control plane anchored to the positive 11J assessment and completed 11I evidence chain.

A valid attempt uses deterministic 51–75% rollout, fresh document eligibility, seven distinct non-requesting reviewers, a separate Admin finalizer, mandatory different-human review, live monitoring, rollback/recovery and an immutable completion hash. Any 11K attempt takes runtime precedence and fails closed without fallback.

## Consequence
A positive 11J result cannot itself widen rollout. Sprint 11K remains bounded and reversible. Sprint 11L must separately measure the 51–75% cohort before any consideration of 76–100% or Production-wide operation.

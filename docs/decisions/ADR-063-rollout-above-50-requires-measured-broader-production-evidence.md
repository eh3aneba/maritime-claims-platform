# ADR-063: Rollout above 50% requires measured broader-production evidence

## Status

Accepted for Sprint 11J.

## Context

Sprint 11I permits a separately authorized 26–50% Production cohort after a positive Sprint 11H recommendation. A successful authorization or completed cohort is not sufficient evidence for wider rollout by itself.

## Decision

Before any design for rollout above 50% or Production-wide operation, the platform must persist a separate Sprint 11J outcome assessment anchored to the exact completed Sprint 11I decision and inherited evidence hashes. The gate measures at least 40 different-human-reviewed runs, workflow representation, quality, grounding, usefulness, human effort, latency, cost, trend regression, incident history, and rollback recovery.

Six independent non-requesting reviewers are required before an Admin can record a recommendation-only outcome. Privacy, Security, or Cross-tenant incident history blocks a positive recommendation even when the incident was later resolved.

## Consequences

A positive 11J result does not widen rollout. It only permits consideration of a separately authorized later stage. Production-wide AI, Restricted documents, new document classes, autonomous claim decisions, and automatic authoritative fact updates remain unauthorized.

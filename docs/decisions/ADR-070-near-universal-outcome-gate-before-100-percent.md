# ADR-070 — Measure near-universal AI before any 100% authorization

## Status
Accepted for Sprint 11Q.

## Context
Sprint 11P can authorize a bounded 91–99% Production AI cohort, but deployment coverage alone is not evidence that the remaining 1–9% can be safely included. Near-universal coverage also increases the consequence of hidden safety, grounding, reliability or workflow-effort regressions.

## Decision
A completed Sprint 11P cohort must pass a separate Sprint 11Q measured outcome gate before a 100% authorization stage may even be designed.

Sprint 11Q:
- re-reads 11P source ledgers rather than trusting aggregate metrics;
- requires at least 160 reviewed runs and 40 per active workflow;
- requires 100% different-human review and observation coverage;
- measures fresh business value including rework, escalation and correction burden;
- permanently blocks a positive recommendation when Privacy, Security or Cross-tenant incident history exists;
- requires twelve independent reviewers plus a separate Admin;
- produces immutable assessment and decision hashes.

## Boundary
A positive Sprint 11Q result is only `recommend_separate_100_percent_authorization_review`. It does not authorize 100%, Production-wide AI, Restricted documents, new document classes, autonomous claim decisions or automatic authoritative fact updates.

## Consequence
Any future Sprint 11R must be separately authorized, expiring, bounded, independently reviewed, monitored, kill-switchable and fail-closed. 100% is never inferred from 99%.

# Sprint 11R — Separately Authorized Bounded 100% Production AI Cohort

## Goal
Allow exactly 100% coverage only inside an explicitly bounded, expiring Production cohort after a positive Sprint 11Q recommendation, while preserving all human-authority and document-scope boundaries.

## Entry criteria
- Sprint 11Q is persisted as `recommended` with `recommend_separate_100_percent_authorization_review`.
- Exact 11Q assessment/decision hashes still match the completed Sprint 11P cohort.
- Completed 11P has no Privacy/Security/Cross-tenant incident history.
- Fresh passing final 11P monitor and complete recovery evidence.

## Authorization
- rollout percentage = 100 exactly;
- max 120 claims / 360 documents / 120 users / 2,000 provider runs;
- max duration 30 days;
- CE Report + Engine Log only;
- Internal / Confidential only;
- exact AI bundle frozen;
- fresh eligibility only; no carry-forward.

## Reviews
Thirteen distinct non-requesting reviewers plus a distinct final Admin:
Security, Privacy, Product, Operations, Risk, Claims Governance, AI Quality, Legal/Data Governance, Business Owner, Platform Reliability, Independent Production Assurance, Data Protection, Executive Production Sponsor.

## Runtime and monitoring
- 11R is the newest fail-closed runtime control plane;
- no fallback to 11P or earlier once an 11R attempt exists;
- 100% different-human review;
- Reject <= 3.5%;
- Edit <= 16%;
- unsupported <= 0.15%;
- grounding >= 99.85%;
- P95 latency <= 13 seconds;
- mean provider cost <= 350,000 micro-USD;
- quality/grounding deterioration <= 50 bps;
- latency/cost regression <= 4%;
- zero open High/Critical incidents;
- zero Privacy/Security/Cross-tenant incident history.

## Completion
- active and unexpired authorization;
- at least 40 fully different-human-reviewed runs;
- at least 10 reviewed runs per active workflow;
- fresh passing final monitor;
- no open incident;
- no safety incident history;
- complete rollback recovery;
- immutable SHA-256 completion hash.

## Non-goals / hard boundaries
Sprint 11R does not authorize unbounded Production-wide use, Restricted documents, new document classes, autonomous coverage/liability/causation/reserve/settlement/payment/recovery decisions, automatic authoritative facts or removal of different-human review.

## Exit
A completed 11R cohort becomes eligible for a separate Sprint 11S measured 100% outcome and enterprise-production-readiness gate. Sprint 11S must still be recommendation-only before any unbounded Production-wide authorization discussion.

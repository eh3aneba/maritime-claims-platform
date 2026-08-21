# AI Final Production Cohort — Sprint 11N

## Purpose
Sprint 11N is the newest Production AI control plane for a separately authorized 76–90% cohort. It is not Production-wide authorization and cannot authorize rollout above 90%.

## Immutable dependency chain
An authorization is valid only while its exact Sprint 11M readiness assessment remains positively recommended and passing. The 11M assessment must still point to the same positive Sprint 11L assessment and completed Sprint 11K authorization. Assessment, decision, completion and inherited rollout hashes plus the provider/model/prompt/schema/input/output bundle are frozen into the 11N authorization.

Any mismatch fails closed.

## Precedence
When the application runs in Production, 11N has precedence over 11K, 11I, 11G and 11E. Once any 11N attempt exists for a tenant, an inactive, pending, held, paused, revoked, completed or expired 11N attempt blocks AI execution. Older authorization stages cannot be used as fallback.

## Authorization envelope
- rollout 76–90% only;
- maximum 30-day lifetime;
- deterministic document bucketing;
- bounded claims, documents, users and provider-run caps;
- `chief_engineer_report` and `engine_log` only;
- Internal/Confidential only;
- fresh per-document legal-basis and data-minimization eligibility;
- no inherited document eligibility.

## Independent authorization
Nine distinct non-requesting reviewers are required: Security, Privacy, Product, Operations, Risk, Claims Governance, AI Quality, Legal/Data Governance and Business Owner. A separate Admin, distinct from the requester and every reviewer, records the final decision.

## Runtime safety
Every provider output requires a different human reviewer. A stale or mismatched bundle, missing fresh eligibility, cap breach, open incident, safety incident history or stale monitor blocks execution. Any incident pauses the authorization. Privacy, Security or Cross-tenant history permanently prevents same-attempt resume.

## Monitoring thresholds
The live monitor enforces 100% human and different-human review, Reject <=5%, Edit <=20%, unsupported output <=0.25%, grounding >=99.75%, P95 latency <=15 seconds, mean provider cost <=400,000 micro-USD, quality/grounding regression <=100 bps and latency/cost regression <=7.5%.

## Hard boundaries
11N does not authorize >90% rollout, Production-wide AI, Restricted documents, new document classes, autonomous claim decisions or automatic authoritative claim-fact updates. Completion only freezes evidence for a later measured outcome gate.

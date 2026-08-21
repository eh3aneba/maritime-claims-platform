# ADR-071: Require bounded 100% evidence before any Production-wide authorization

## Status
Accepted for Sprint 11R.

## Context
Sprint 11Q can recommend a separate 100% authorization review after measuring the 91–99% near-universal cohort. A 100% percentage, however, can be misunderstood as permission for unrestricted Production-wide use. The platform still has intentionally narrow document, confidentiality, human-review and tenant boundaries.

## Decision
Introduce Sprint 11R as a separately authorized **bounded 100% Production AI cohort**. A positive 11Q recommendation is necessary but not sufficient: thirteen independent human approvals and a distinct Admin decision are required, with fresh document eligibility and an expiring capped authorization.

Once any 11R attempt exists, runtime must fail closed on that newest control plane and may not fall back to 11P or earlier stages.

The authorization may cover 100% of eligible items only inside its explicit bounded cohort. `production_wide_unbounded_authorized` remains false. Restricted documents, new document classes, autonomous claim decisions, automatic authoritative facts and removal of different-human review remain prohibited.

## Consequences
- 100% rollout becomes technically possible without equating it to unrestricted deployment.
- Every run remains traceable to fresh eligibility, a frozen model/prompt/schema bundle and a different-human review.
- A failing monitor pauses the cohort and triggers rollback controls.
- Safety incident history requires a new authorization attempt.
- Completion is evidence for a later measured 100% outcome/enterprise-readiness gate, not permission to broaden scope.

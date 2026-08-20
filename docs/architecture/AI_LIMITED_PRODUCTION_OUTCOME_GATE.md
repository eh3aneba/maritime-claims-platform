# Sprint 11F — Limited-Production Outcome Gate

## Purpose

Sprint 11F measures one completed Sprint 11E limited-production authorization. It converts the bounded Production cohort into a content-free, immutable outcome package and a human recommendation. It does **not** expand rollout or create Production-wide authorization.

## Anchor and immutability

Each assessment is anchored to:

- one completed `ai_limited_production_authorizations` record;
- the exact authorization decision hash;
- the exact model, prompt bundle and schema bundle;
- the exact recorded rollout percentage.

The assessment fails closed if the anchor is no longer completed or any pinned bundle field differs when the scorecard is finalized. Failed, rejected, extended and stopped attempts remain historical; a correction requires a new append-only assessment attempt.

## Per-run evidence

Every limited-production run must already be `human_reviewed` with an immutable `outcome_hash`. Sprint 11F then requires one content-free observation per run containing only:

- usefulness rating;
- reviewer effort in seconds;
- unsupported-output count;
- source-grounded output count and denominator;
- workflow-completion flag;
- bounded artifact/runbook/ticket/monitor reference;
- human note.

Document text, prompts, provider responses, candidate values, source quotes, personal data and secrets are outside this ledger.

## Fixed exit thresholds

The `limited_production_graduation_v1` profile requires:

- 100% human-review coverage;
- 100% outcome-observation coverage;
- 100% workflow completion;
- Reject rate <= 10%;
- Edit rate <= 35%;
- mean usefulness >= 4.2/5;
- unsupported-output rate <= 1%;
- source-grounding validity >= 99%;
- mean human review time <= 480 seconds;
- P95 latency <= 20 seconds;
- mean observed provider cost <= 500,000 micro-USD per run;
- no material second-half quality regression above 500 bps;
- no material second-half mean-latency or mean-cost increase above 20%;
- zero unresolved High/Critical incidents;
- zero Privacy, Security or Cross-tenant incidents, even if later resolved.

When both CE Reports and Engine Logs were represented in the authorized document cohort, both must also be represented in provider-run evidence.

## Trend model

Runs are ordered by queue time and divided deterministically into first and second halves. Quality regression is the worst positive deterioration across Reject rate, Edit rate, unsupported-output rate and source-grounding validity. Latency and cost regressions are relative second-half increases versus the first half. Missing second-half evidence fails closed.

## Human decision chain

A passing frozen scorecard requires four independent approvals:

1. Product
2. Quality
3. Risk
4. Operations

All four reviewers must be different people and none may be the assessment requester. An Administrator then records exactly one outcome:

- `recommend_graduation_stage`
- `extend_limited_production_evaluation`
- `stop_ai_progression`

A positive result is recommendation-only. It cannot increase the rollout, authorize new document classes, admit Restricted documents, enable autonomous claims decisions or update authoritative claim facts automatically.

## Audit and tenant isolation

Creation, observation capture, scorecard finalization, reviews and the Admin decision are tenant-scoped and audit logged. The assessment and final decision are frozen with canonical SHA-256 snapshots.

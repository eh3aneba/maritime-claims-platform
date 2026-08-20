# Private-Pilot Outcome Gate

Sprint 11D measures a completed Sprint 11C real-document private pilot. It converts the content-free run ledger into a deterministic cohort scorecard and an independently reviewed exit recommendation. It never authorizes Production.

## Lifecycle

1. A Manager creates an append-only assessment anchored to one completed private-pilot attempt.
2. An operator records one content-free usability observation for every human-reviewed pilot run. Workflow type, latency, observed provider cost and human action are read from the immutable 11C run; they are not re-entered.
3. Finalization freezes the complete run and observation hashes, fixed thresholds, per-workflow scorecards, cost trend, incident trend and deterministic failure reasons.
4. Only a passing assessment may receive Product, Quality and Risk reviews. The three reviewers must be different people and none may be the requester.
5. An Administrator records one outcome: recommend a separately authorized limited-production evaluation, require another bounded private-pilot attempt, or stop AI progression.

Failed and finalized attempts are immutable. New evidence requires a new attempt where the lifecycle permits one.

## Fixed `private_pilot_exit_v1` profile

- at least six reviewed runs: three Chief Engineer Reports and three Engine Logs
- 100% human-review, workflow-observation, workflow-completion and safety-boundary coverage
- no more than 20% Reject and 50% Edit actions
- mean usefulness of at least 4/5
- mean human-review time of no more than 600 seconds
- P95 provider latency of no more than 30 seconds
- mean observed provider cost of no more than 500,000 micro-USD per run
- zero unresolved incidents, zero Critical incidents and zero Privacy/Security/Cross-tenant incidents

Thresholds are server-owned database constraints. Clients cannot relax them.

## Evidence and trend model

The outcome ledger stores run IDs, run outcome hashes, workflow class, usefulness rating, review seconds, completion/boundary flags, bounded evidence references, aggregate counts and SHA-256 snapshots. It computes first-half versus second-half mean observed cost and incident totals by severity. It also emits separate CE Report and Engine Log scorecards.

Document text, prompts, provider outputs, source quotes, candidate values, personal data, credentials and calculated provider billing are excluded.

## Authorization boundary

`recommend_limited_production_evaluation` is a recommendation to design and review a new authorization. Every API response states `production_authorized: false`. The recommendation cannot enable a provider, widen document classes, admit Restricted documents, bypass human review, update authoritative facts or make liability, coverage, reserve, settlement or payment decisions.

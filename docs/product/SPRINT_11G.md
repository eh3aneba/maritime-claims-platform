# Sprint 11G — Controlled AI Scale-Up Authorization

## Goal

Allow a separately reviewed 11–25% Production cohort only after Sprint 11F records a positive graduation recommendation. The stage is deliberately bounded and cannot grant Production-wide, Restricted-document or autonomous claim-decision authority.

## Delivered controls

- exact Sprint 11F assessment/decision hash anchoring
- completed Sprint 11E and exact AI bundle revalidation
- deterministic 11–25% rollout only
- fixed claim/document/user/provider-run quotas and <=30-day expiry
- five independent Security/Privacy/Product/Operations/Risk approvals
- Admin-only authorize/hold decision with canonical SHA-256 snapshot
- fresh per-document legal-basis/data-minimization/change eligibility
- queue-time and worker-time fail-closed runtime gates
- no fallback to the older 11E authorization after an 11G attempt exists
- content-free provider-run ledger with different-human review
- unsupported-output and source-grounding measurements
- live review/quality/grounding/latency/cost/regression monitoring
- incident pause, rollback, separate resolution, monitor-gated Admin resume
- safety incidents requiring a fresh authorization rather than same-attempt resume
- explicit kill switch and fail-closed completion
- tenant API and operator dashboard
- migration, lifecycle/safety tests, architecture note and ADR-060

## Fixed boundaries

- CE Report and Engine Log only
- non-Restricted documents only
- rollout <=25%
- 100% human review
- Reject <=10%
- Edit <=35%
- unsupported output <=1%
- source grounding >=99%
- P95 latency <=20 seconds
- mean observed provider cost <=500,000 micro-USD/run
- zero open incidents
- zero Privacy/Security/Cross-tenant incidents for successful continuation/completion
- no material second-half quality, latency or cost regression

## Non-goals

Sprint 11G does not authorize Production-wide traffic, rollout above 25%, Restricted documents, new document classes, autonomous liability/coverage/reserve/settlement/payment decisions, or automatic authoritative claim-fact updates.

## Exit

A completed controlled cohort may be measured by a later, separate outcome gate. Completion itself cannot widen the rollout. Any consideration of broader Production use requires new evidence, independent review and a separate authorization stage.

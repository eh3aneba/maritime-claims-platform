# Sprint 11N — Separately Authorized Final Production AI Cohort

## Objective
Operate one explicit, expiring 76–90% Production AI cohort only after a positive Sprint 11M recommendation. Sprint 11N does not authorize Production-wide AI or rollout above 90%.

## Entry gate
The exact Sprint 11M assessment must remain `recommended` with outcome `recommend_separate_final_production_authorization`, overall pass, zero failed controls and intact assessment/decision hashes. Its Sprint 11L and completed Sprint 11K anchors plus inherited rollout hashes and the exact AI bundle must continue to match.

## Authorization
Nine different non-requesting reviewers are required: Security, Privacy, Product, Operations, Risk, Claims Governance/Compliance, AI Quality/Model Governance, Legal/Data Governance and Business Owner/Claims Director. The final Admin is a tenth distinct actor and cannot be the requester.

## Scope
- rollout 76–90%;
- <=30 days;
- deterministic cohort;
- bounded claim/document/user/provider-run caps;
- CE Report and Engine Log only;
- Internal/Confidential only;
- fresh legal-basis/data-minimization eligibility for every document;
- no eligibility carry-forward.

## Runtime controls
11N is the newest Production AI control plane and never falls back to an older stage after an 11N attempt exists. Every output requires different-human review. Live monitors enforce quality, grounding, latency, cost, regression and incident thresholds. Any incident pauses the cohort; safety-boundary history blocks same-attempt resume.

## Completion
Completion requires every run to have different-human review, no open incidents, no Privacy/Security/Cross-tenant history, fresh passing final monitoring and complete rollback-recovery evidence. Completion creates an immutable hash but grants no new rollout permission.

## Hard boundaries
Sprint 11N never authorizes rollout above 90%, Production-wide AI, Restricted documents, new document classes, autonomous liability/coverage/reserve/settlement/payment/recovery decisions, automatic authoritative claim facts or removal of different-human review.

## Next stage
A separate Sprint 11O measured outcome gate must evaluate completed 76–90% evidence before any 91–100% / Production-wide question can be considered.

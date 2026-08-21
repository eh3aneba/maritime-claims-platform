# Sprint 11P — Separately Authorized Near-Universal Production AI Cohort (91–99%)

## Objective
Authorize one bounded, expiring 91–99% Production AI cohort only after a positive Sprint 11O recommendation. Sprint 11P does not authorize 100% rollout or Production-wide AI.

## Entry gate
The exact Sprint 11O assessment must be `recommended` with outcome `recommend_separate_91_100_authorization_review`, `overall_pass=true`, zero failure reasons and intact assessment/decision hashes. The completed Sprint 11N authorization behind it must retain matching decision/completion hashes, exact provider/model/prompt/schema/input/output bundle, allowed document classes, prior rollout and prior caps.

## Envelope
- rollout: 91–99% only;
- maximum duration: 21 days;
- deterministic document buckets;
- bounded claims/documents/users/provider-run caps;
- CE Report and Engine Log only;
- Internal/Confidential only;
- fresh per-document legal-basis/data-minimization/change-ticket evidence;
- no previous eligibility carry-forward.

## Independent authorization
Eleven distinct non-requesting reviewers are required: Security, Privacy, Product, Quality, Operations, Risk, Claims Governance/Compliance, AI Quality/Model Governance, Legal/Data Governance, Business Owner/Claims Director and Platform Reliability/SRE. The final Admin must be distinct from the requester and all eleven reviewers.

Admin outcomes:
- `authorize_near_universal_91_99_cohort`
- `hold_for_remediation`
- `reject_progression`

## Runtime
Any Sprint 11P attempt becomes the newest Production AI control plane. Inactive, pending, held, paused, rejected, revoked, completed or expired 11P states fail closed and never fall back to 11N/11K/11I/11G/11E.

Every provider run requires a different-human review. The exact authorized model/prompt/schema/output-token bundle and input limit must remain intact.

## Live thresholds
- human review = 100%;
- different-human review = 100%;
- Reject <=4%;
- Edit <=18%;
- unsupported <=0.20%;
- grounding >=99.80%;
- P95 latency <=14s;
- mean provider cost <=375,000 micro-USD/run;
- quality/grounding regression <=75 bps;
- latency regression <=5%;
- cost regression <=5%;
- zero open High/Critical incidents;
- zero Privacy/Security/Cross-tenant incident history.

## Incident and recovery
Any incident pauses execution immediately. Privacy/Security/Cross-tenant history permanently blocks same-attempt resume. Non-safety recovery requires all incidents resolved, a later fresh passing monitor, complete recovery evidence and explicit Admin resume. Rollback SLO is 15 minutes and no automatic resume is allowed.

## Completion
Completion requires at least one run, all runs reviewed by different humans, no open incidents, no safety-boundary history, fresh passing final monitoring, complete non-safety recovery evidence and intact anchor/bundle/caps. Completion produces an immutable SHA-256 hash and grants no additional permission.

## Hard boundaries
Sprint 11P always keeps false:
- `rollout_100_percent_authorized`;
- `production_wide_authorized`;
- `restricted_documents_authorized`;
- `new_document_classes_authorized`;
- `autonomous_claim_decisions_authorized`;
- `authoritative_facts_auto_updated`;
- removal of different-human review.

## Next stage
Sprint 11Q must independently measure the completed 91–99% cohort before 100% or Production-wide AI can even be recommended. No automatic widening is permitted.

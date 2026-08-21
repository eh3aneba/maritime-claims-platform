# AI High-Coverage Authorization — Sprint 11K

Sprint 11K adds a separately authorized, expiring Production AI control plane for a deterministic 51–75% document cohort. It can only be created after a positive Sprint 11J recommendation and a completed Sprint 11I broader-production cohort.

Each authorization freezes the Sprint 11J assessment/decision hashes, completed Sprint 11I decision hash, inherited 11H/11G/11F hashes, exact model/prompt/schema/input/output bundle, prior rollout and requested rollout. Queue-time and worker-time checks revalidate that chain.

Seven distinct non-requesting reviewers are required: Security, Privacy, Product, Operations, Risk, Claims Governance/Compliance and AI Quality/Model Governance. A separate Admin then records the final authorize/hold/reject decision.

Any 11K attempt becomes the newest Production control plane. Held, paused, rejected, revoked, completed or expired 11K attempts fail closed and never fall back to 11I/11G/11E.

Only CE Report and Engine Log documents with Internal or Confidential classification are eligible. Fresh legal-basis and data-minimization evidence is mandatory. Every provider run is content-free in the control ledger and requires a different human reviewer.

Live thresholds are: 100% review, Reject <=6%, Edit <=25%, unsupported <=0.50%, grounding >=99.50%, P95 latency <=18s, mean cost <=450,000 micro-USD/run, quality/grounding regression <=200 bps, latency/cost regression <=10%, zero open High/Critical incidents and zero Privacy/Security/Cross-tenant incident history. Failed monitors pause execution and create a rollback incident.

Non-safety recovery requires incident resolution, a later fresh passing monitor and explicit Admin recovery. Safety-boundary incidents permanently block resume for the attempt. Completion requires all runs reviewed, complete recovery evidence, a fresh passing monitor and an immutable completion hash.

Hard boundaries remain: no rollout above 75%, no Production-wide AI, no Restricted documents, no new document classes, no autonomous claim decisions, no automatic authoritative claim-fact updates and no raw provider/document content in the governance ledger.

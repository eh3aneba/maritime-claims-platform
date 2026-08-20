# External AI Activation Roadmap

## Current capability

The product already has a provider-neutral gateway, an OpenAI adapter using the Responses API and strict Structured Outputs, source-linked extraction candidates, quote verification, confidence fields, append-only feedback and mandatory Approve/Edit/Reject human review. AI candidates never directly update authoritative claim facts. The external provider remains disabled by default, and Sprint 11A blocks restricted documents entirely.

Deterministic tests may still inject local fake providers, but real OpenAI processing is restricted to a separately governed staging environment. Configuration alone is not authorization.

## Sprint 11A — Provider Activation & Evaluation Gate

Implementation status: the application control plane, independent approval ledger, per-document eligibility gate, kill switch and queue-time enforcement are implemented. Shared staging processing still requires the organization to provision and evidence the separate provider project, secret, spend, privacy and incident controls and then complete an authorized activation attempt.

- separate OpenAI staging and production projects and credentials (operational prerequisite; Sprint 11A authorizes staging only)
- secret-manager/environment-only key handling; no database, source or log storage
- explicit document-classification allowlist and restricted-data prohibition by default
- pinned provider, model, extraction schema and prompt versions
- per-run character/token limits, rate limits, monthly spend ceiling and kill switch
- retention, residency, legal/privacy and incident-owner decisions
- immutable activation request with independent security/privacy and product approvals
- no automatic enabling of production or restricted documents

Exit: after the operational prerequisites and independent activation decision are complete, the staging provider may be enabled for synthetic/de-identified evaluation only.

## Sprint 11B — Quality, Safety & Cost Evaluation

Implementation status: the application now provides the version-pinned, content-free case ledger, deterministic threshold calculation, independent reviews, Admin promotion decision and revocation control. The organization must still execute the controlled synthetic/de-identified benchmark against its authorized staging provider and record the observed evidence before promotion.

- representative synthetic/de-identified CE reports and engine logs
- field-level precision/recall and unsupported-claim rate
- source-quote validity and page/segment linkage
- prompt-injection, malformed-file, cross-tenant and restricted-data tests
- latency, token and cost budgets
- regression suite pinned to model/prompt/schema versions
- human-review usability and override measurements

Exit: all fixed thresholds pass, Quality/Risk reviews are independently completed and an Admin records the expiring staging promotion. Failures block promotion and remain visible.

## Sprint 11C — Bounded Real-Document Private Pilot

Implementation status: the application now provides the append-only pilot authorization, independent organization/data-owner approvals, Admin decision, document-level eligibility, queue-time enforcement, content-free run ledger, mandatory different-human review, incident pause/resume, quota enforcement, completion gate and kill switch. Actual real-document processing still requires the organization to supply the bounded evidence, obtain the approvals and authorize the cohort; code deployment alone is not data-processing authorization.

- explicit organization and data-owner authorization
- allowlisted non-restricted document types only
- small case/time/user cohort with mandatory human review
- monitoring, incident response, immediate provider kill switch and rollback
- no autonomous liability, coverage, reserve, settlement or payment decision
- outcome review before any scope expansion
- content-free run/outcome ledger with a different human reviewer for every provider run

Exit: a separately authorized production-AI decision may be considered. Restricted documents remain a later explicit decision.

## Sprint 11D — Private-Pilot Outcome & Exit Gate

Implementation status: the application now provides an append-only assessment anchored to a completed Sprint 11C pilot, one content-free usability observation per reviewed run, deterministic cohort/workflow scorecards, incident and cost trends, independent Product/Quality/Risk reviews and an Admin exit recommendation.

- minimum six reviewed runs with three CE Reports and three Engine Logs
- complete human-review, workflow-observation and safety-boundary coverage
- fixed Reject/Edit, usefulness, review-effort, latency and observed-cost thresholds
- zero unresolved/Critical incidents and zero privacy/security/cross-tenant incidents
- immutable failures and SHA-256 evidence snapshots
- recommend limited-production evaluation, extend private pilot or stop progression
- every result preserves `production_authorized: false`

Exit: a limited-production evaluation control plane may be designed only after a positive recommendation. That later control plane and its authorization remain separate decisions.

## Sprint 11E — Limited-Production Evaluation

Implementation status: the application now provides the separate authorization chain, exact-bundle pinning, deterministic 1–10% document rollout, fixed time/cohort quotas, document-level eligibility, queue and worker enforcement, different-human run review, live quality/cost/latency monitoring, incident rollback, Admin recovery, expiry, completion and kill switch. Actual Production evaluation still requires the organization to provision the isolated provider controls, supply the bounded evidence, complete four independent approvals and explicitly authorize the attempt.

- positive Sprint 11D recommendation as an anchor, not an authorization
- isolated Production deployment/project/credential/data-processing/change evidence
- non-Restricted CE Report and Engine Log allowlist only
- deterministic rollout plus claim, document, user and provider-run caps
- fixed rollback SLO, monitor cadence and review/quality/latency/cost thresholds
- 100% different-human review and content-free outcome ledger
- fail-closed pause on monitor failure or incident
- separate incident resolution, recovery monitor and Admin resume
- no automatic Production-wide, Restricted-data or autonomous-decision permission

Exit: the bounded evaluation may be completed only after every run is reviewed, incidents are resolved and a fresh monitor passes. Completion creates no wider authorization.

## Sprint 11F — Limited-Production Outcome Gate

Planned: measure the completed 11E cohort, operational drift, incidents, rollback performance, quality, latency, observed cost and human effort; then require independent review before an Admin records stop, extend or consider-graduation. Any wider rollout remains a later, separate authorization.

## Practical answer

- Deterministic developer tests: available now with local fake providers and no external processing.
- Shared staging use: after Sprint 11A controls are deployed and an activation attempt is independently authorized.
- Real but non-restricted CE reports and engine logs: after Sprints 11A and 11B pass, Sprint 11C is deployed, its independent approvals are complete and an Admin explicitly authorizes the bounded cohort and document.
- Pilot exit recommendation: after Sprint 11D passes every fixed outcome threshold, three independent reviews complete and an Admin records the recommendation.
- Limited 1–10% Production evaluation: after Sprint 11E is deployed, its isolated operational evidence and four independent approvals are complete, an Admin authorizes the exact attempt, and each document is separately eligible.
- Production-wide and Restricted-document use: still unauthorized; each requires a separate future control plane and explicit decision.

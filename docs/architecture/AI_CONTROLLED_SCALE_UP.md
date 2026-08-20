# Sprint 11G — Controlled AI Scale-Up Architecture

## Purpose

Sprint 11G introduces a separate, expiring Production authorization for a measured increase from the completed Sprint 11E cohort. It exists only after a positive Sprint 11F graduation recommendation and does not convert that recommendation into permission automatically.

## Immutable anchors

Every scale-up attempt freezes:

- Sprint 11F assessment ID, assessment SHA-256 and decision SHA-256
- completed Sprint 11E authorization ID and its decision hash through the 11F snapshot
- exact provider model, prompt bundle, schema bundle, input limit and output-token limit
- the previously measured rollout percentage
- the newly requested rollout percentage

The service re-checks the frozen 11F and 11E anchors at authorization time, document admission, runtime execution and resume.

## Authorization boundary

The new rollout must be:

- greater than the measured Sprint 11E percentage
- between 11% and 25% inclusive
- limited to the exact CE Report and Engine Log allowlist measured previously
- time-boxed to no more than 30 days
- bounded by claims, documents, users and provider-run quotas

Five distinct non-requesting reviewers are required: Security, Privacy, Product, Operations and Risk. An Administrator records the final authorize/hold decision. The decision is hashed from a canonical content-free snapshot.

## Fresh document admission

Sprint 11E eligibility never carries forward. Each 11G document requires a fresh legal-basis, data-minimization and change-control attestation. The current document must:

- belong to the tenant and claim
- be the current evidence version
- be non-Restricted
- be a CE Report or Engine Log
- fall inside the deterministic SHA-256 rollout bucket
- remain within authorization quotas

## Queue-time and worker-time enforcement

`app.modules.ai_runtime` is the unified runtime facade. In Production:

1. If no Sprint 11G attempt exists, the existing Sprint 11E control plane remains applicable.
2. Once any Sprint 11G attempt exists, 11G becomes the tenant's Production control plane.
3. A pending, held, paused, revoked, completed or expired 11G attempt cannot fall back to 11E.
4. An active 11G attempt must pass the exact bundle, tenant, document, confidentiality, rollout, quota, incident and monitor gates.

The API uses the facade before queueing. The document worker installs the same facade before processing queued AI jobs, so revocation, pause, expiry and monitor changes are effective at execution time as well.

## Content-free run ledger

Each provider run records only identifiers and observed operational counters. A different human must review each run and record:

- Approve/Edit/Reject
- candidate and edit counts
- unsupported-output count
- grounded-source count and checked-source count
- latency
- observed provider cost
- bounded evidence reference
- SHA-256 outcome snapshot

Document text, prompts, provider responses, candidate answers, source quotes, personal data and secrets are excluded from this control ledger.

## Live monitoring and rollback

A live monitor calculates:

- 100% human-review coverage
- Reject rate <= 10%
- Edit rate <= 35%
- unsupported-output rate <= 1%
- source-grounding validity >= 99%
- P95 latency <= 20 seconds
- mean observed provider cost <= 500,000 micro-USD/run
- first-half vs second-half quality, latency and cost regression
- open incidents and safety-boundary incident history

Any failure records `rollback_required` and pauses the authorization. Incidents also pause immediately. Resolution never resumes automatically; a fresh passing monitor and explicit Admin resume are required. Privacy, Security or Cross-tenant incidents require a new authorization attempt rather than resume.

## Completion

Completion requires every provider run to have different-human review, no open incidents, no Privacy/Security/Cross-tenant incident history and a fresh passing monitor. Completion creates no wider authorization.

## Explicit non-goals

Sprint 11G never authorizes:

- rollout above 25%
- Production-wide AI traffic
- Restricted documents
- new document classes
- autonomous liability, coverage, reserve, settlement or payment decisions
- automatic authoritative claim-fact updates
- automatic scope expansion or self-renewal
